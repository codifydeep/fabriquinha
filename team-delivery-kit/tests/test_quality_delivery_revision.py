"""Correction dispatch fixtures, not a live author or complete revision loop."""
import json
import unittest
from unittest.mock import patch
from broker import quality_delivery_revision as revision
import test_quality_delivery_review_attestation as fixtures


class DeliveryRevisionTests(unittest.TestCase):
    def setUp(self):
        f=fixtures.DeliveryAttestationTests();f.setUp();self.addCleanup(f.doCleanups)
        self.f=f;self.b=f.b;self.request=f.request;self.b.QUALITY_DELIVERY_REVISION_ENABLED=True
        self.finding=dict(criterion=f.assignment['plan']['criteria'][0],path='app.py',line=1,quote='VALUE=1',
            expected='A complete behavior',observed='Only a fixture constant')
        f.update(action='request_changes',findings=[self.finding]);self.receipt=f.call()
        self.wakeup=dict(id='b0000000-0000-4000-8000-000000000001',agent_id=f.assignment['author'],issue_id=f.c['issue_id'])

    def register(self):return revision.register(self.b,self.request)

    def test_register_preserves_rejected_candidate_and_exact_freeze_for_original_author(self):
        context,state=self.register();self.assertEqual(self.register(),(context,state))
        self.assertEqual(context['author'],self.f.assignment['author']);self.assertEqual(context['origin_task'],self.f.c['task_id'])
        self.assertEqual(context['seed'],self.f.assignment['snapshot'])
        self.assertEqual(context['seed_manifest_sha256'],self.f.c['manifest_sha256'])
        self.assertEqual(context['review_receipt_sha256'],revision.quality.digest(self.receipt))
        self.assertEqual(context['editable_paths'],['/workspace/'+p for p in sorted(context['plan']['product_files'])])
        self.assertFalse(set(context['editable_paths'])&{'/workspace/'+p for p in context['frozen_tests']})
        self.assertEqual(state['stage'],'prepared');self.assertFalse(state['execution_authorized'])

    def test_dispatch_is_once_and_targets_original_implementer_not_reviewer(self):
        with patch.object(revision.review.native,'ensure_scope_author_start',return_value=self.wakeup) as wake:
            result=revision.dispatch(self.b,self.request)
            self.assertEqual(revision.dispatch(self.b,self.request),result)
        wake.assert_called_once();self.assertEqual(wake.call_args.args[2],self.f.assignment['author'])
        self.assertEqual(wake.call_args.args[3],self.f.c['task_id']);self.assertTrue(wake.call_args.kwargs['allow_create'])
        self.assertEqual(result['stage'],'awaiting_product_revision_admission');self.assertFalse(result['merge_authorized'])

    def test_lost_ack_observes_same_marker_and_never_posts_again(self):
        with patch.object(revision.review.native,'ensure_scope_author_start',side_effect=TimeoutError) as wake:
            for _ in range(2):
                with self.assertRaises(revision.validation_job.Pending):revision.dispatch(self.b,self.request)
        self.assertTrue(wake.call_args_list[0].kwargs['allow_create']);self.assertFalse(wake.call_args_list[1].kwargs['allow_create'])
        self.assertEqual(wake.call_args_list[0].args,wake.call_args_list[1].args)
        with patch.object(revision.review.native,'ensure_scope_author_start',return_value=self.wakeup) as wake:
            result=revision.dispatch(self.b,self.request)
        self.assertFalse(wake.call_args.kwargs['allow_create']);self.assertEqual(result['stage'],'awaiting_product_revision_admission')

    def test_unknown_ack_expires_to_cto_without_same_condition_retry(self):
        with patch.object(revision.review.native,'ensure_scope_author_start',side_effect=TimeoutError),self.assertRaises(revision.validation_job.Pending):
            revision.dispatch(self.b,self.request)
        context,state=revision.load(self.b,self.request)
        with patch.object(revision.time,'time',return_value=state['deadline']+1),patch.object(revision.review.native,'ensure_scope_author_start',return_value=None):
            result=revision.dispatch(self.b,self.request)
        self.assertEqual(result['stage'],'technical_blocked');self.assertEqual(result['owner'],context['cto'])
        with patch.object(revision.review.native,'ensure_scope_author_start') as wake:
            self.assertEqual(revision.dispatch(self.b,self.request),result);wake.assert_not_called()

    def test_capacity_wait_retains_deadline_alerts_and_then_escalates(self):
        with self.b.db() as con:
            for n in (1,2):con.execute('INSERT INTO leases(request_id,status) VALUES(?,?)',('busy-'+str(n),'running'))
        with patch.object(revision.review.native,'ensure_scope_author_start') as wake:
            for now in (1000,1700):
                with patch.object(revision.time,'time',return_value=now),self.assertRaises(revision.validation_job.Pending):revision.dispatch(self.b,self.request)
            context,state=revision.load(self.b,self.request);self.assertEqual(state['capacity_since'],1000);self.assertTrue(state['alert_due'])
            with patch.object(revision.time,'time',return_value=2801):result=revision.dispatch(self.b,self.request)
            wake.assert_not_called()
        self.assertEqual(result['stage'],'technical_blocked');self.assertEqual(result['owner'],context['cto'])

    def test_pending_revision_reserves_original_author_and_global_slot(self):
        with patch.object(revision.review.native,'ensure_scope_author_start',return_value=self.wakeup):revision.dispatch(self.b,self.request)
        with self.b.db() as con:
            self.assertFalse(revision.review.available(con,self.f.assignment['author'],1000))
            self.assertTrue(revision.review.available(con,self.f.assignment['cto'],1000))
            con.execute('INSERT INTO leases(request_id,status) VALUES(?,?)',('other-slot','running'))
            self.assertFalse(revision.review.available(con,self.f.assignment['cto'],1000))

    def test_maintenance_and_disabled_flag_prevent_dispatch(self):
        self.b.QUALITY_DELIVERY_REVISION_ENABLED=False
        with patch.object(revision.review.native,'ensure_scope_author_start') as wake,self.assertRaises(ValueError):revision.dispatch(self.b,self.request)
        wake.assert_not_called();self.b.QUALITY_DELIVERY_REVISION_ENABLED=True
        with self.b.db() as con:con.execute('INSERT INTO controller_maintenance VALUES(?,?,?)',('operator','sealed',json.dumps(dict(stage='sealed'))))
        with patch.object(revision.review.native,'ensure_scope_author_start') as wake,self.assertRaises(revision.validation_job.Pending):revision.dispatch(self.b,self.request)
        wake.assert_not_called()

    def test_stale_validation_receipt_cannot_become_a_correction_handoff(self):
        with self.b.db() as con:con.execute("DELETE FROM validation_jobs WHERE json_extract(identity,'$.kind')='delivery_review'")
        with self.assertRaises(ValueError):self.register()

    def test_frozen_test_finding_goes_to_cto_without_author_wakeup(self):
        f=fixtures.DeliveryAttestationTests();f.setUp();self.addCleanup(f.doCleanups)
        path=next(p for p in f.files if p.startswith('tests/'))
        line=f.files[path].decode().splitlines()[0]
        finding=dict(criterion=f.assignment['plan']['criteria'][0],path=path,line=1,quote=line,
            expected='Review the contract',observed='The frozen test requires technical analysis')
        f.update(action='request_changes',findings=[finding]);f.call();f.b.QUALITY_DELIVERY_REVISION_ENABLED=True
        with patch.object(revision.review.native,'ensure_scope_author_start') as wake:
            result=revision.dispatch(f.b,f.request)
        wake.assert_not_called();self.assertEqual(result['stage'],'technical_blocked')
        self.assertEqual(result['owner'],f.assignment['cto']);self.assertEqual(result['incident']['category'],'frozen_contract_finding')


if __name__=='__main__':unittest.main()
