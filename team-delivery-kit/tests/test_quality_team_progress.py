"""Automatic v2 handoffs using durable native fixtures, not live qualification."""
import copy
import json
import ast
import sys
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
from broker import quality_team_progress as team
import test_quality_test_review as reviews
import test_quality_delivery_capture as deliveries
import test_quality_review_attestation as attestations


def configured(b):
    b.QUALITY_TEAM_ENABLED=True;b.QUALITY_IMPLEMENTATION_ENABLED=True
    for name in team.IMAGES:
        if not getattr(b,name,None):setattr(b,name,'sha256:'+'a'*64)


class TeamProgressTests(unittest.TestCase):
    def setUp(self):
        f=reviews.QualityTestReviewTests();f.setUp();self.addCleanup(f.doCleanups)
        self.f=f;self.b=f.b;self.source=f.source;configured(self.b)

    def call(self):return team.tick(self.b,limit=1)

    def test_review_ready_automatically_dispatches_once_without_test_approval(self):
        with patch.object(team.review.native,'ensure_review_start',return_value=self.f.wakeup) as wake:
            state=self.call()['observed'][0]
            again=self.call()['observed'][0]
        wake.assert_called_once()
        self.assertEqual(state['stage'],'awaiting_review_admission')
        self.assertEqual(again['stage'],'awaiting_review_admission')
        self.assertEqual(state['owner'],self.f.e.reviewer)
        self.assertFalse(state['delivery_approval']);self.assertFalse(state['green_approved'])

    def test_full_capacity_queues_before_native_wakeup_and_continues_when_freed(self):
        with self.b.db() as con:
            for i in (1,2):con.execute('INSERT INTO leases(request_id,status) VALUES(?,?)',('occupied-'+str(i),'running'))
        with patch.object(team.review.native,'ensure_review_start',return_value=self.f.wakeup) as wake:
            self.assertEqual(self.call()['observed'][0]['stage'],'waiting_review_capacity');wake.assert_not_called()
            with self.b.db() as con:con.execute('DELETE FROM leases WHERE request_id LIKE ?',('occupied-%',))
            self.assertEqual(self.call()['observed'][0]['stage'],'awaiting_review_admission')
        wake.assert_called_once()

    def test_lost_dispatch_ack_is_observed_without_a_second_create(self):
        with patch.object(team.review.native,'ensure_review_start',side_effect=TimeoutError) as wake:
            for _ in range(2):self.assertEqual(self.call()['observed'][0]['stage'],'waiting_review_dispatch')
        self.assertTrue(wake.call_args_list[0].kwargs['allow_create'])
        self.assertFalse(wake.call_args_list[1].kwargs['allow_create'])

    def test_returned_approval_without_persistent_attestation_cannot_start_implementation(self):
        self.f.dispatch();self.f.admit()
        with patch.object(team.attestation,'observe',return_value=dict(stage='tests_frozen',tests_approved=True)),\
                patch.object(team.implementation,'dispatch') as implement:
            state=self.call()['observed'][0]
        self.assertEqual(state['stage'],'technical_blocked');implement.assert_not_called()

    def test_default_off_missing_configuration_and_maintenance_never_dispatch(self):
        with patch.object(team.review.native,'ensure_review_start') as wake:
            self.b.QUALITY_TEAM_ENABLED=False;self.assertEqual(self.call()['stage'],'disabled')
            self.b.QUALITY_TEAM_ENABLED=True;self.b.QUALITY_GREEN_JOB_IMAGE=None
            self.assertEqual(self.call()['stage'],'configuration_blocked')
            self.b.QUALITY_GREEN_JOB_IMAGE='sha256:'+'a'*64
            with self.b.db() as con:
                con.execute('INSERT INTO controller_maintenance VALUES(?,?,?)',('operator','sealed',json.dumps(dict(stage='sealed'))))
            self.assertEqual(self.call()['stage'],'maintenance')
        wake.assert_not_called()

    def test_stage_wait_has_fixed_deadline_and_escalates_to_cto_not_ceo(self):
        self.f.dispatch()
        for now in (1000,1700):
            with patch.object(team.time,'time',return_value=now):state=self.call()['observed'][0]
        self.assertTrue(state['alert_due']);self.assertEqual(state['phase_deadline'],2800)
        with patch.object(team.time,'time',return_value=2801):state=self.call()['observed'][0]
        self.assertEqual(state['stage'],'technical_blocked');self.assertEqual(state['owner'],self.b.QUALITY_CTO)

    def test_bad_authority_is_quarantined_without_starving_the_next_card(self):
        bad='00000000-0000-4000-8000-000000000001'
        with self.b.db() as con:
            con.execute('INSERT INTO quality_author_admissions VALUES(?,?,?,?,?)',('other',bad,'untrusted','{}','0'*64))
        self.assertEqual(self.call()['observed'][0]['stage'],'technical_blocked')
        with patch.object(team.review.native,'ensure_review_start',return_value=self.f.wakeup):
            self.assertEqual(self.call()['observed'][0]['stage'],'awaiting_review_admission')
        self.assertEqual(team.status(self.b)['quarantine'][0]['source_task'],bad)

    def test_two_pending_sources_receive_alternating_observation_after_restart(self):
        other='90000000-0000-4000-8000-000000000009';request='90000000-0000-4000-8000-000000000010'
        issue='90000000-0000-4000-8000-000000000011';run='90000000-0000-4000-8000-000000000012'
        with self.b.db() as con:
            config,receipt=con.execute('SELECT config,receipt FROM quality_lifecycle_enrollments').fetchone()
            config,receipt=json.loads(config),json.loads(receipt)
            config['plan'].update(issue_id=issue,run_id=run)
            receipt.update(issue_id=issue,run_id=run,plan_sha256=team.quality.digest(config['plan']))
            con.execute('INSERT INTO quality_lifecycle_enrollments VALUES(?,?,?,?,?)',
                (issue,run,json.dumps(config),json.dumps(receipt),team.quality.digest(receipt)))
            original=team.author.load(con,'req');c=copy.deepcopy(original)
            c.update(issue_id=issue,task_id=other,request_id=request,scope='fixture:'+other,run_id=run,
                plan_sha256=receipt['plan_sha256'],enrollment_sha256=team.quality.digest(receipt))
            c['issue']['id']=issue
            con.execute('INSERT INTO grants(request_id,task_id,attempt,mode,used,deadline,digest) VALUES(?,?,?,?,?,?,?)',
                (request,other,1,'implementation',1,0,'f'*64))
            con.execute('INSERT INTO native_bindings VALUES(?,?,?,?,?)',(request,other,c['agent_id'],c['scope'],issue))
            con.execute('INSERT INTO quality_native_scopes VALUES(?,?,?,?,?)',(request,other,run,'tests_only_v2',c['plan_sha256']))
            con.execute('INSERT INTO quality_author_admissions VALUES(?,?,?,?,?)',
                (issue,other,request,json.dumps(c),team.quality.digest(c)))
        with patch.object(team,'advance',side_effect=lambda b,identity,phase:team.outcome('waiting_author',identity['author'])):
            seen=[self.call()['observed'][0]['source_task'] for _ in range(4)]
        self.assertEqual(seen,[self.source,other,self.source,other])

    def test_configuration_failure_is_durable_and_disables_old_partial_tick(self):
        self.b.QUALITY_GREEN_JOB_IMAGE=None
        self.assertEqual(self.call()['stage'],'configuration_blocked')
        self.assertEqual(team.status(self.b)['health']['stage'],'configuration_blocked')
        with patch.object(team.progress,'advance') as legacy:
            self.assertEqual(team.progress.tick(self.b)['stage'],'team_managed')
        legacy.assert_not_called()

    def test_unknown_saved_stage_is_quarantined_not_interpreted_as_homologation(self):
        with patch.object(team.review.native,'ensure_review_start',return_value=self.f.wakeup):self.call()
        with self.b.db() as con:
            state=json.loads(con.execute('SELECT state FROM quality_team_progress').fetchone()[0])
            state['stage']='HOMOLOGADA'
            con.execute('UPDATE quality_team_progress SET state=?,state_sha256=?',
                (json.dumps(state),team.quality.digest(state)))
        with patch.object(team.review.native,'ensure_review_start') as wake:
            self.assertEqual(self.call()['observed'],[])
        wake.assert_not_called()
        self.assertEqual(team.status(self.b)['quarantine'][0]['stage'],'technical_blocked')

    def test_status_before_first_tick_is_readonly_and_reports_unobserved(self):
        with self.b.db() as con:before=list(con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"))
        self.assertEqual(team.status(self.b)['health']['stage'],'unobserved')
        with self.b.db() as con:after=list(con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"))
        self.assertEqual([tuple(r) for r in before],[tuple(r) for r in after])

    def test_late_observation_checks_new_durable_progress_before_escalating_old_view(self):
        self.f.dispatch()
        with patch.object(team.time,'time',return_value=1000):self.call()
        self.f.admit()
        with patch.object(team.time,'time',return_value=2801),\
                patch.object(team.attestation,'observe',side_effect=team.validation_job.Pending('same review stream')):
            state=self.call()['observed'][0]
        self.assertEqual(state['stage'],'waiting_test_review')
        self.assertEqual(state['phase_deadline'],4601)
        self.assertFalse(state['green_approved'])

    def test_actual_watchdog_hook_invokes_team_once_and_preserves_cycle_barrier(self):
        # Compile only the repository-owned watchdog function, never start the
        # candidate HTTP server or touch the installed controller database.
        path=Path(__file__).resolve().parents[1]/'broker/server.py'
        tree=ast.parse(path.read_bytes());main=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='main')
        watchdog=next(n for n in main.body if isinstance(n,ast.FunctionDef) and n.name=='watchdog')
        class StopWatchdog(BaseException):pass
        calls=[]
        def sleep(seconds):
            calls.append(seconds)
            if len(calls)==10:raise StopWatchdog()
        barrier=SimpleNamespace(begin_cycle=Mock(return_value=True),end_cycle=Mock())
        namespace=dict(tick=Mock(),handoff_context=lambda:self.b,controller_maintenance=barrier,
            QUALITY_TEAM_ENABLED=True,QUALITY_V2_ENABLED=True,time=SimpleNamespace(sleep=sleep),json=json,
            reconcile_review_outcomes=Mock(),reconcile_review_retries=Mock(),reconcile_change_requests=Mock(),
            handoff_runtime=SimpleNamespace(tick=Mock()))
        imports={n.name:Mock() for node in ast.walk(watchdog) if isinstance(node,ast.Import) for n in node.names}
        imports.update(quality_team_progress=team,quality_progress=team.progress)
        exec(compile(ast.Module(body=[watchdog],type_ignores=[]),str(path),'exec'),namespace)
        with patch.dict(sys.modules,imports),\
                patch.object(team.review.native,'ensure_review_start',return_value=self.f.wakeup) as wake,\
                self.assertRaises(StopWatchdog):namespace['watchdog']()
        wake.assert_called_once();barrier.begin_cycle.assert_called_once_with(self.b)
        barrier.end_cycle.assert_called_once_with(self.b)
        self.assertEqual(team.status(self.b)['tasks'][0]['stage'],'awaiting_review_admission')


class TeamDeliveryTests(unittest.TestCase):
    def test_frozen_review_automatically_dispatches_original_author_once(self):
        f=attestations.QualityReviewAttestationTests();f.setUp();self.addCleanup(f.doCleanups);f.call();configured(f.b)
        source=f.source;plan=f.f.f.capture.plan
        wakeup=dict(id='90000000-0000-4000-8000-000000000001',issue_id=plan['issue_id'],agent_id=plan['author'])
        with patch.object(team.implementation.native,'ensure_scope_author_start',return_value=wakeup) as wake:
            for _ in range(2):
                result=team.tick(f.b)['observed'][0]
                self.assertEqual(result['stage'],'awaiting_implementation_admission')
        wake.assert_called_once();self.assertFalse(result['green_approved'])

    def test_frozen_tests_admitted_implementation_advances_to_durable_copy_not_delivery(self):
        f=deliveries.DeliveryCaptureTests();f.setUp();self.addCleanup(f.doCleanups);configured(f.b)
        with patch.object(team.delivery.validation_job,'run',side_effect=f.copied):
            state=team.tick(f.b,limit=1)['observed'][0]
        self.assertEqual(state['stage'],'awaiting_git_binding')
        self.assertFalse(state['green_approved']);self.assertFalse(state['delivery_approval'])
        with patch.object(team.delivery,'observe',side_effect=AssertionError('no replay')):
            self.assertEqual(team.tick(f.b)['observed'][0]['stage'],'awaiting_git_binding')

    def test_registered_candidate_releases_green_without_restarting_author_or_review(self):
        f=deliveries.DeliveryCaptureTests();f.setUp();self.addCleanup(f.doCleanups);configured(f.b)
        with patch.object(team.delivery.validation_job,'run',side_effect=f.copied):team.tick(f.b,limit=1)
        result=dict(stage='awaiting_sensitivity',green_approved=False,delivery_approval=False)
        with patch.object(team.candidate,'load',return_value=({},{})),\
                patch.object(team.green,'observe',return_value=result) as observe,\
                patch.object(team.green,'load',side_effect=[None,({},result)]):
            state=team.tick(f.b,limit=1)['observed'][0]
        observe.assert_called_once_with(f.b,f.request)
        self.assertEqual(state['stage'],'awaiting_sensitivity');self.assertFalse(state['delivery_approval'])

    def test_pending_green_is_observed_under_techlead_not_misreported_as_red(self):
        f=deliveries.DeliveryCaptureTests();f.setUp();self.addCleanup(f.doCleanups);configured(f.b)
        with patch.object(team.delivery.validation_job,'run',side_effect=f.copied):team.tick(f.b,limit=1)
        with patch.object(team.candidate,'load',return_value=({},{})),\
                patch.object(team.green,'observe',side_effect=team.validation_job.Pending('original Green running')):
            result=team.tick(f.b,limit=1)['observed'][0]
        self.assertEqual(result['stage'],'waiting_green');self.assertEqual(result['owner'],f.b.QUALITY_TECHLEAD)

    def test_persisted_green_triggers_negative_control_not_another_green_job(self):
        f=deliveries.DeliveryCaptureTests();f.setUp();self.addCleanup(f.doCleanups);configured(f.b)
        with patch.object(team.delivery.validation_job,'run',side_effect=f.copied):team.tick(f.b,limit=1)
        result=dict(stage='awaiting_independent_delivery_review',delivery_approval=False)
        with patch.object(team.candidate,'load',return_value=({},{})),\
                patch.object(team.green,'load',return_value=({},dict(stage='awaiting_sensitivity'))),\
                patch.object(team.green,'observe',side_effect=AssertionError('no replay Green')),\
                patch.object(team.sensitivity,'observe',return_value=result) as observe,\
                patch.object(team.sensitivity,'load',return_value=({},result)):
            state=team.tick(f.b,limit=1)['observed'][0]
        observe.assert_called_once_with(f.b,f.request)
        self.assertEqual(state['stage'],'awaiting_independent_delivery_review');self.assertFalse(state['delivery_approval'])
        self.assertEqual(team.tick(f.b)['observed'],[])


if __name__=='__main__':unittest.main()
