import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from broker import generic_calibration_red_bridge as bridge,handoffs,test_first_handoffs,template_author_executor
from test_test_first_handoffs import Broker


class RedBridgeTests(unittest.TestCase):
    def setUp(self):
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        self.b=Broker(Path(directory.name)/'db')
        self.route=dict(issue_id='issue',cto='cto')
        self.source=dict(id='author')
        self.pending=dict(stage='policy_review_wait',owner='reviewer',execution_authorized=False,
            delivery_approval=False,required_action='Observe original native review')
        self.prepared=dict(manifest_sha256='a'*64,test_sha256={'tests/test.py':'b'*64})
        self.record=dict(context={'candidate_volume':'frozen'},policy=dict(
            candidate_manifest_sha256='a'*64,test_sha256=self.prepared['test_sha256']))
        with self.b.db() as con:handoffs.initialize(con)

    def test_pending_requests_original_workflow_without_registration_or_test_execution(self):
        with patch.object(bridge.workflow,'request',return_value=self.pending) as request,\
                patch.object(bridge.registration,'register') as register,patch.object(bridge.gate,'run') as run:
            with self.b.db() as con:
                with self.assertRaises(bridge.Pending) as caught:
                    bridge.capture(self.b,con,'issue','author','frozen',self.prepared)
            self.assertEqual(caught.exception.state,self.pending)
            request.assert_called_once_with(self.b,'issue','author');register.assert_not_called();run.assert_not_called()

    def test_ready_revalidates_exact_registration_and_actual_receipt_not_product_red(self):
        receipt=dict(delivery_approval=False,red_approved=False)
        with patch.object(bridge.workflow,'request',return_value=dict(stage='calibration_ready',calibration_receipt=receipt)),\
                patch.object(bridge.registration,'register',return_value=self.record),\
                patch.object(bridge.gate,'run',return_value={'receipt':receipt}) as run:
            with self.b.db() as con:
                self.assertEqual(bridge.capture(self.b,con,'issue','author','frozen',self.prepared),receipt)
                with self.assertRaises(ValueError):bridge.capture(self.b,con,'issue','author','other',self.prepared)
            self.assertEqual(run.call_count,1)

    def test_native_review_wait_does_not_inherit_expired_generic_job_timer(self):
        prior=dict(data=json.dumps({'validation_wait':{'first_seen':0},'original':'preserved'}))
        self.assertTrue(bridge.observe(self.b,self.route,self.source,prior,bridge.Pending('issue','author',self.pending)))
        with self.b.db() as con:row=handoffs.load(con,'author')
        self.assertEqual(row['stage'],'test_first_validation_pending')
        data=json.loads(row['data']);self.assertNotIn('validation_wait',data)
        self.assertEqual(data['original'],'preserved');self.assertFalse(data['author_retry_authorized'])

    def test_owned_block_remains_visible_without_prescribing_test_repair_or_retry(self):
        blocked={**self.pending,'stage':'blocked','category':'native_review_deadline','owner':'cto'}
        bridge.observe(self.b,self.route,self.source,None,bridge.Pending('issue','author',blocked))
        with self.b.db() as con:row=handoffs.load(con,'author')
        self.assertEqual(row['stage'],'test_first_blocked')
        self.assertEqual(json.loads(row['data'])['error'],'generic_calibration_prerequisite:native_review_deadline')
        with self.b.db() as con:con.execute('CREATE TABLE test_first_red(issue_id TEXT,task_id TEXT,receipt TEXT)')
        with patch.object(template_author_executor,'observe'),\
                patch.object(test_first_handoffs,'technical_recovery') as legacy:
            source={**self.source,'status':'completed','agent_id':'author','created_at':'now'}
            self.assertIsNone(test_first_handoffs.reconcile(self.b,{**self.route,'author':'author'},[source],object()))
            legacy.assert_not_called()

    def test_unrelated_timeout_keeps_existing_job_handling_and_other_binding_is_rejected(self):
        self.assertFalse(bridge.observe(self.b,self.route,self.source,None,TimeoutError()))
        with self.assertRaises(ValueError):
            bridge.observe(self.b,self.route,self.source,None,bridge.Pending('other','author',self.pending))

    def test_durable_calibration_restores_legacy_overwrite_without_legacy_repair_or_event_loop(self):
        source={**self.source,'status':'completed','agent_id':'author','created_at':'now'}
        route={**self.route,'author':'author'}
        blocked={**self.pending,'stage':'blocked','category':'bundle_task_failed','owner':'cto'}
        with self.b.db() as con:
            bridge.workflow.initialize(con)
            con.execute('INSERT INTO generic_calibration_workflows VALUES(?,?,?,?)',
                ('issue','author','{}',json.dumps(blocked)))
            con.execute('CREATE TABLE test_first_red(issue_id TEXT,task_id TEXT,receipt TEXT)')
            handoffs.save(con,'author','issue','test_first_blocked','cto',
                dict(source_task='author',phase='test_first',error='test_first_correction_failed_after_cto_diagnosis'),0)
        with patch.object(template_author_executor,'observe'),patch.object(bridge.workflow,'request',return_value=blocked),\
                patch.object(test_first_handoffs,'technical_recovery') as legacy:
            test_first_handoffs.reconcile(self.b,route,[source],object())
            with self.b.db() as con:
                restored=handoffs.load(con,'author');count=con.execute('SELECT count(*) FROM delivery_handoff_events').fetchone()[0]
            data=json.loads(restored['data']);self.assertEqual(data['calibration_prerequisite'],blocked)
            self.assertEqual(data['calibration_projection_repair']['prior_error'],'test_first_correction_failed_after_cto_diagnosis')
            test_first_handoffs.reconcile(self.b,route,[source],object());legacy.assert_not_called()
            with self.b.db() as con:self.assertEqual(con.execute('SELECT count(*) FROM delivery_handoff_events').fetchone()[0],count)
