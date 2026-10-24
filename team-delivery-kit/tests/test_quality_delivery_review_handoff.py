"""Controller/native fixtures, not live delivery-review or model qualification."""
import copy
import json
import time
import unittest
from unittest.mock import patch
from broker import quality_delivery_review_handoff as handoff
import test_quality_sensitivity_capture as fixtures


class DeliveryReviewHandoffTests(unittest.TestCase):
    def setUp(self):
        f=fixtures.SensitivityCaptureTests();f.setUp();self.addCleanup(f.doCleanups);self.f=f;self.b=f.b;self.request=f.request
        with patch.object(fixtures.capture.validation_job,'run',side_effect=f.job):f.call()
        self.b.QUALITY_DELIVERY_REVIEW_ENABLED=True
        self.task='a0000000-0000-4000-8000-000000000001'
        self.wakeup=dict(id='a0000000-0000-4000-8000-000000000002',
            issue_id=fixtures.capture.load(self.b,self.request)[0]['plan']['issue_id'],
            agent_id=fixtures.capture.load(self.b,self.request)[0]['plan']['reviewer'])
        self.current=None
        task_record=handoff.native.task_record;task_runs=handoff.native.issue_task_runs
        def lookup(settings,task,agent):
            return self.current if task==self.task else task_record(settings,task,agent)
        def runs(*args):return task_runs(*args)+([self.current] if self.current else [])
        for name,fn in (('task_record',lookup),('issue_task_runs',runs)):
            p=patch.object(handoff.native,name,side_effect=fn);p.start();self.addCleanup(p.stop)

    def prepare(self):return handoff.prepare(self.b,self.request)

    def dispatch(self):
        with patch.object(handoff.native,'ensure_review_start',return_value=self.wakeup):
            return handoff.dispatch(self.b,self.request)

    def native_task(self):
        self.dispatch();context,state=handoff.load(self.b,self.request)
        settings=json.loads((self.b.STATE/'native.json').read_bytes())
        self.current=dict(id=self.task,agent_id=context['reviewer'],issue_id=context['issue_id'],
            workspace_id=settings['workspace_id'],runtime_id=settings['runtime_id'],status='running',
            created_at='2026-10-24T12:00:00Z',wakeup_id=state['wakeup_id'],
            handoff_note=handoff.note(context))
        return context,state

    def admit(self):return handoff.admit(self.b,self.request,self.task,self.current['agent_id'])

    def test_prepare_binds_all_quality_evidence_without_creating_grants_or_jobs(self):
        with self.b.db() as con:before=con.execute('SELECT count(*) FROM grants').fetchone()[0]
        context,state=self.prepare();self.assertEqual(self.prepare(),(context,state))
        self.assertEqual(state['stage'],'prepared')
        self.assertEqual(context['manifest_sha256'],context['evidence']['green']['manifest_sha256'])
        self.assertEqual(context['commit_sha'],context['evidence']['green']['commit_sha'])
        self.assertEqual(set(context['read_paths']),{'/delivery/'+p for p in context['file_inventory']})
        self.assertFalse(state['execution_authorized']);self.assertFalse(state['delivery_approval'])
        with self.b.db() as con:self.assertEqual(con.execute('SELECT count(*) FROM grants').fetchone()[0],before)

    def test_dispatch_is_once_and_a_restart_observes_its_registered_wakeup(self):
        with patch.object(handoff.native,'ensure_review_start',return_value=self.wakeup) as wake:
            result=handoff.dispatch(self.b,self.request)
            self.assertEqual(handoff.dispatch(self.b,self.request),result)
        wake.assert_called_once();self.assertEqual(result['stage'],'awaiting_delivery_review_admission')
        self.assertTrue(wake.call_args.kwargs['allow_create'])

    def test_unknown_dispatch_ack_never_reposts_and_late_ack_uses_same_marker(self):
        with patch.object(handoff.native,'ensure_review_start',side_effect=TimeoutError) as wake:
            for _ in range(2):
                with self.assertRaises(handoff.validation_job.Pending):handoff.dispatch(self.b,self.request)
        self.assertTrue(wake.call_args_list[0].kwargs['allow_create'])
        self.assertFalse(wake.call_args_list[1].kwargs['allow_create'])
        self.assertEqual(wake.call_args_list[0].args,wake.call_args_list[1].args)
        with patch.object(handoff.native,'ensure_review_start',return_value=self.wakeup) as late:
            result=handoff.dispatch(self.b,self.request)
        self.assertFalse(late.call_args.kwargs['allow_create'])
        self.assertEqual(result['stage'],'awaiting_delivery_review_admission')

    def test_unknown_ack_expires_to_visible_cto_incident_without_resetting_intent(self):
        with patch.object(handoff.native,'ensure_review_start',side_effect=TimeoutError):
            with self.assertRaises(handoff.validation_job.Pending):handoff.dispatch(self.b,self.request)
        context,before=handoff.load(self.b,self.request)
        with patch.object(handoff.time,'time',return_value=before['deadline']+1),\
                patch.object(handoff.native,'ensure_review_start',return_value=None) as wake:
            result=handoff.dispatch(self.b,self.request)
        self.assertFalse(wake.call_args.kwargs['allow_create'])
        self.assertEqual(result['stage'],'technical_blocked');self.assertEqual(result['owner'],context['cto'])
        self.assertFalse(result['incident']['automatic_retry'])
        with patch.object(handoff.native,'ensure_review_start') as wake:
            self.assertEqual(handoff.dispatch(self.b,self.request),result);wake.assert_not_called()

    def test_global_capacity_is_bounded_and_no_native_wakeup_is_issued_while_full(self):
        with self.b.db() as con:
            for n in (1,2):con.execute('INSERT INTO leases(request_id,status) VALUES(?,?)',('occupied-'+str(n),'running'))
        with patch.object(handoff.native,'ensure_review_start',return_value=self.wakeup) as wake:
            with self.assertRaises(handoff.validation_job.Pending):handoff.dispatch(self.b,self.request)
            wake.assert_not_called()
            with self.b.db() as con:con.execute("DELETE FROM leases WHERE request_id LIKE 'occupied-%'")
            self.assertEqual(handoff.dispatch(self.b,self.request)['stage'],'awaiting_delivery_review_admission')
        wake.assert_called_once()

    def test_starvation_has_one_persistent_deadline_and_a_technical_owner(self):
        with self.b.db() as con:
            for n in (1,2):con.execute('INSERT INTO leases(request_id,status) VALUES(?,?)',('occupied-'+str(n),'running'))
        with patch.object(handoff.native,'ensure_review_start') as wake:
            for now in (1000,1700):
                with patch.object(handoff.time,'time',return_value=now),self.assertRaises(handoff.validation_job.Pending):
                    handoff.dispatch(self.b,self.request)
            context,state=handoff.load(self.b,self.request)
            self.assertEqual(state['capacity_since'],1000);self.assertTrue(state['alert_due'])
            with patch.object(handoff.time,'time',return_value=2801):result=handoff.dispatch(self.b,self.request)
            self.assertEqual(result['stage'],'technical_blocked');self.assertEqual(result['owner'],context['cto'])
            wake.assert_not_called()

    def test_exact_native_admission_mints_one_distinct_readonly_phase_not_approval(self):
        context,_=self.native_task();grant=self.admit()
        with self.b.db() as con:admitted=handoff.admission(con,grant['request_id'])
        self.assertEqual(admitted['phase'],'delivery_review_v2');self.assertEqual(admitted['mode'],'review')
        self.assertEqual(admitted['snapshot_volume'],context['snapshot']['volume'])
        self.assertEqual(admitted['commit_sha'],context['commit_sha'])
        self.assertNotEqual(grant['request_id'],self.request)
        self.assertNotEqual(admitted['task_id'],context['origin_task'])
        self.assertEqual(admitted['editable_paths'],[])
        self.assertFalse(admitted['delivery_approval'])
        with self.assertRaises(ValueError):self.admit()

    def test_foreign_wakeup_role_runtime_status_or_issue_cannot_mint_a_grant(self):
        self.native_task()
        for key,value in (('wakeup_id',self.task),('status','completed'),('runtime_id','foreign'),
                ('agent_id',self.b.QUALITY_CTO),('issue_id',self.task),('handoff_note','claimed authority')):
            before=self.current[key];self.current[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):self.admit()
            self.current[key]=before
        with self.b.db() as con:self.assertEqual(con.execute('SELECT count(*) FROM quality_delivery_review_admissions').fetchone()[0],0)

    def test_admission_revalidates_frozen_snapshot_incarnation(self):
        self.native_task();self.f.f.f.volume['CreatedAt']='recreated'
        with self.assertRaises(ValueError):self.admit()

    def test_false_or_missing_fixed_job_evidence_cannot_become_handoff_authority(self):
        context,state=fixtures.capture.load(self.b,self.request)
        key=state['observation']['validation_job_key']
        with self.b.db() as con:con.execute('DELETE FROM validation_jobs WHERE job_key=?',(key,))
        with patch.object(handoff.native,'ensure_review_start') as wake,self.assertRaises(ValueError):self.prepare()
        wake.assert_not_called()

    def test_newer_unregistered_review_task_cannot_borrow_old_review_history(self):
        context,_=self.native_task();original=handoff.native.issue_task_runs
        foreign={**self.current,'id':'a0000000-0000-4000-8000-000000000099','status':'completed'}
        with patch.object(handoff.native,'issue_task_runs',side_effect=lambda *a:original(*a)+[foreign]):
            with self.assertRaises(ValueError):self.admit()

    def test_disabled_or_maintenance_never_dispatches_or_partially_admits(self):
        self.b.QUALITY_DELIVERY_REVIEW_ENABLED=False
        with patch.object(handoff.native,'ensure_review_start') as wake,self.assertRaises(ValueError):self.dispatch()
        wake.assert_not_called();self.b.QUALITY_DELIVERY_REVIEW_ENABLED=True
        with self.b.db() as con:
            con.execute('INSERT INTO controller_maintenance VALUES(?,?,?)',('operator','sealed',json.dumps(dict(stage='sealed'))))
        with patch.object(handoff.native,'ensure_review_start') as wake,self.assertRaises(handoff.validation_job.Pending):self.dispatch()
        wake.assert_not_called()

    def test_admission_record_cannot_change_to_test_review_or_another_commit(self):
        self.native_task();grant=self.admit()
        with self.b.db() as con:
            row=con.execute('SELECT context FROM quality_delivery_review_admissions').fetchone()
            original=json.loads(row[0])
            for mutation in (dict(phase='test_review_v2'),dict(commit_sha='0'*40),dict(editable_paths=['/delivery/app.py'])):
                altered={**original,**mutation}
                con.execute('UPDATE quality_delivery_review_admissions SET context=?,context_sha256=?',
                    (json.dumps(altered),handoff.quality.digest(altered)))
                with self.subTest(mutation=mutation),self.assertRaises(ValueError):handoff.admission(con,grant['request_id'])
            con.execute('UPDATE quality_delivery_review_admissions SET context=?,context_sha256=?',
                (json.dumps(original),handoff.quality.digest(original)))

    def test_nonfinite_or_boolean_time_cannot_issue_an_invalid_capability_deadline(self):
        self.native_task()
        for now in (True,float('nan'),float('inf'),-1):
            with self.subTest(now=now),self.assertRaises(ValueError):
                handoff.admit(self.b,self.request,self.task,self.current['agent_id'],now=now)
        with self.b.db() as con:
            self.assertEqual(con.execute('SELECT count(*) FROM quality_delivery_review_admissions').fetchone()[0],0)

    def test_completed_delivery_filters_only_registered_prior_author_lineage(self):
        from broker import quality_test_revision as revision
        context,state=handoff.delivery.load(self.b,self.request);author=context['admission']['agent_id']
        original=handoff.native.issue_task_runs
        previous=dict(id='a0000000-0000-4000-8000-000000000077',agent_id=author,status='completed')
        with patch.object(handoff.native,'issue_task_runs',side_effect=lambda *a:original(*a)+[previous]):
            with self.assertRaises(ValueError):self.prepare()
            with patch.object(revision,'exclude_prior_authors',side_effect=lambda b,source,items:
                    [r for r in items if r['id']!=previous['id']]) as registered:
                result=self.prepare()
            self.assertEqual(result[1]['stage'],'prepared')
            self.assertEqual(registered.call_args.args[1],context['admission']['source_task'])

    def test_admission_and_validation_recheck_the_review_revision_lineage(self):
        from broker import quality_test_revision as revision
        context,_=self.native_task()
        with patch.object(revision,'exclude_prior_reviews',wraps=revision.exclude_prior_reviews) as prior:
            grant=self.admit();handoff.current(self.b,grant['request_id'])
        self.assertGreaterEqual(prior.call_count,2)
        self.assertTrue(all(c.args[1]==context['source_task'] for c in prior.call_args_list))

    def reserve_other_handoff(self):
        context,state=self.prepare();other='a0000000-0000-4000-8000-000000000088'
        queued={**context,'implementation_request':other}
        pending={**state,'stage':'dispatch_intent','deadline':time.time()+600}
        with self.b.db() as con:con.execute('INSERT INTO quality_delivery_review_handoffs VALUES(?,?,?,?,?)',
            (other,json.dumps(queued),json.dumps(pending),handoff.quality.digest(queued),handoff.quality.digest(pending)))
        return context,state,other

    def test_pending_native_handoff_reserves_the_profile_before_a_worker_exists(self):
        _,_,other=self.reserve_other_handoff()
        with patch.object(handoff.native,'ensure_review_start',return_value=self.wakeup) as wake:
            with self.assertRaises(handoff.validation_job.Pending):handoff.dispatch(self.b,self.request)
            wake.assert_not_called()
            with self.b.db() as con:con.execute('DELETE FROM quality_delivery_review_handoffs WHERE implementation_request=?',(other,))
            self.assertEqual(handoff.dispatch(self.b,self.request)['stage'],'awaiting_delivery_review_admission')
        wake.assert_called_once()

    def test_dispatch_intent_rechecks_reservation_under_the_shared_transaction_lock(self):
        context,state,_=self.reserve_other_handoff()
        with self.assertRaises(handoff.validation_job.Pending):
            handoff.save(self.b,self.request,context,state,{**state,'stage':'dispatch_intent','deadline':time.time()+600})
        self.assertEqual(handoff.load(self.b,self.request)[1]['stage'],'prepared')


if __name__=='__main__':unittest.main()
