import copy
import json
import sqlite3
import unittest
from broker import generic_calibration_protocol_recovery as repair,generic_calibration_workflow as workflow,handoffs
from generic_harness_calibration import digest


class ProtocolRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.con=sqlite3.connect(':memory:');self.con.row_factory=sqlite3.Row;self.addCleanup(self.con.close)
        workflow.initialize(self.con);handoffs.initialize(self.con)
        self.c=dict(issue_id='issue',author_task='author',cto='cto',reviewer='lead',test_files=['tests/test_one.py'],criteria={'A01':'preserved'})
        self.s=dict(stage='blocked',category='bundle_task_failed',observed_task='failed',wakeup_id='old-wake',
            execution_authorized=False,delivery_approval=False)
        self.t=dict(id='failed',agent_id='cto',issue_id='issue',wakeup_id='old-wake',status='failed',failure_reason='agent_error.provider_server_error')
        self.b=dict(task_id='failed',agent_id='cto',issue_id='issue',request_id='execution',status='closed',scope='workspace:cto:planning:failed')
        self.event=dict(event='model_proxy_request',status=502,category='structured_decision_response_invalid',execution_id='execution',
            call_number=1,decision_schema='delivery_decision_v1',strict_schema=True,structured_rejection_category='schema_violation',
            structured_rejection_diagnostic=dict(version='structured-constraint-v1',constraints=['maxItems'],upstream_sha256='a'*64))
        self.barrier=dict(stage='sealed',namespace='delivery-kit-port2',drained=True,operation_id='maintenance')
        self.sources={name:'b'*64 for name in repair.SOURCES}
        self.con.execute('INSERT INTO generic_calibration_workflows VALUES(?,?,?,?)',('issue','author',json.dumps(self.c),json.dumps(self.s)))
        handoffs.save(self.con,'author','issue','test_first_blocked','cto',dict(calibration_prerequisite=self.s,
            error='generic_calibration_prerequisite:bundle_task_failed',source_task='author'),0)

    def state(self):return json.loads(self.con.execute('SELECT state FROM generic_calibration_workflows').fetchone()[0])
    def migrate(self,**changes):
        args=dict(c=self.c,state=self.state(),task=self.t,binding=self.b,tool_count=0,event=self.event,
            barrier=self.barrier,namespace='delivery-kit-port2',sources=self.sources,now=1)
        args.update(changes)
        return repair.transition(self.con,**args)

    def test_one_migration_preserves_failure_and_reopens_only_prerequisite(self):
        receipt=self.migrate();state=self.state()
        self.assertEqual(receipt['prior_state'],self.s);self.assertEqual(state['stage'],'bundle_dispatch')
        self.assertEqual(state['protocol_recovery_sha256'],digest(receipt))
        parent=handoffs.load(self.con,'author');self.assertEqual(parent['stage'],'test_first_validation_pending')
        self.assertFalse(receipt['author_restarted']);self.assertFalse(receipt['tests_executed'])
        self.assertFalse(state['delivery_approval']);self.assertFalse(state['execution_authorized'])
        self.assertEqual(self.migrate(),receipt)
        self.assertEqual(self.con.execute('SELECT count(*) FROM generic_calibration_protocol_recoveries').fetchone()[0],1)
        self.assertEqual(self.con.execute('SELECT count(*) FROM delivery_handoff_events').fetchone()[0],2)

    def test_changed_facts_or_used_tools_cannot_trigger_recovery(self):
        for override in (dict(tool_count=1),dict(tool_count=False),dict(task={**self.t,'agent_id':'author'}),
                dict(task={**self.t,'status':'running'}),dict(binding={**self.b,'status':'running'}),
                dict(event={**self.event,'status':200}),dict(event={**self.event,'execution_id':'foreign'}),
                dict(barrier={**self.barrier,'stage':'released'}),dict(sources={}),
                dict(event={**self.event,'structured_rejection_diagnostic':{**self.event['structured_rejection_diagnostic'],'constraints':['required']}})):
            with self.subTest(override=override),self.assertRaises(ValueError):self.migrate(**override)
        self.assertEqual(self.state(),self.s)

    def test_artifacts_or_foreign_parent_forbid_migration(self):
        self.con.execute('CREATE TABLE generic_calibration_proposals(issue_id TEXT,author_task TEXT)')
        self.con.execute("INSERT INTO generic_calibration_proposals VALUES('issue','author')")
        with self.assertRaises(ValueError):self.migrate()
        self.con.execute('DELETE FROM generic_calibration_proposals')
        self.con.execute("UPDATE delivery_handoffs SET stage='done'")
        with self.assertRaises(ValueError):self.migrate()
        self.assertEqual(self.state(),self.s)

    def test_restart_does_not_reset_or_repeat_failed_recovery(self):
        receipt=self.migrate();state=self.state();state.update(stage='blocked',category='bundle_task_failed',observed_task='second-failure')
        self.con.execute('UPDATE generic_calibration_workflows SET state=?',(json.dumps(state),))
        self.assertEqual(self.migrate(),receipt);self.assertEqual(self.state(),state)
        with self.assertRaises(ValueError):self.migrate(event={**self.event,'call_number':2})

    def test_recovered_dispatch_has_new_identity_and_observes_lost_ack(self):
        receipt=self.migrate();events=[]
        class Effects:
            def verify(_,c):pass
            def reserve(_,c):return True
            def wake(_,c,note,marker,first):
                events.append((marker,first));raise TimeoutError()
        fx=Effects()
        workflow.advance(self.con,self.c,fx,now=2)
        workflow.advance(self.con,self.c,fx,now=3)
        old=digest(dict(config_sha256=digest(self.c),phase='bundle',protocol='generic-calibration-producer-v1'))
        self.assertNotEqual(events[0][0],old);self.assertEqual(events[0][0],events[1][0])
        self.assertEqual([e[1] for e in events],[True,False])
        self.assertEqual(repair.qualified(self.con,self.c,self.state()),receipt)

    def test_drifted_or_fabricated_state_cannot_dispatch(self):
        self.migrate();state=self.state();state['protocol_recovery_sha256']='f'*64
        with self.assertRaises(ValueError):repair.qualified(self.con,self.c,state)

    def test_parent_save_failure_rolls_back_both_workflow_and_receipt(self):
        from unittest.mock import patch
        with patch.object(handoffs,'save',side_effect=ValueError('storage failed')):
            with self.assertRaises(ValueError):self.migrate()
        self.assertEqual(self.state(),self.s)
        self.assertEqual(self.con.execute('SELECT count(*) FROM generic_calibration_protocol_recoveries').fetchone()[0],0)
