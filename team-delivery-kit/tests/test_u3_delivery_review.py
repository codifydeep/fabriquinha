import copy
import io
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch, Mock

from broker import u3_delivery_review as review
from broker import durable_review_job as jobs


class FinalCoverageReviewTests(unittest.TestCase):
    def fixture(self):
        parent = dict(contract=dict(manifest_sha256='a'*64), reviewer='planning',
            intake=dict(cto='cto', controls_config=dict(author='author')))
        state = dict(stage='integration_review_approved', receipt=dict(task='prior'), publication=dict(
            coverage_head_sha=review.HEAD, coverage_pr=review.PR, coverage_ci='success',
            predecessor_merged_sha=review.BASE, predecessor_main_ci='success', merge_authorized=False))
        config = dict(parent_contract_sha256=review.digest(parent['contract']),
            parent_review_sha256=review.digest(state['receipt']), manifest_sha256='a'*64,
            head_sha=review.HEAD, base_sha=review.BASE, pr_url=review.PR, reviewer=review.REVIEWER,
            issue_id='child')
        return parent, state, config, dict(agents={review.REVIEWER:'review'})

    def evidence(self):
        _, _, config, _ = self.fixture()
        state = dict(wakeup_id='wake')
        task = dict(id='task', status='completed', agent_id=review.REVIEWER, issue_id='child', wakeup_id='wake')
        decision = dict(review_task_id='task', status='approved', source_task_id='source',
            reviewer_agent_id=review.REVIEWER, manifest_sha256='a'*64)
        suite = dict(review_task='task', source_task='source', manifest_sha256='a'*64, tests=261,
            exit_code=0, executed_by='controller_offline_review_suite', network='none', snapshot_mount='readonly')
        reads = {p:dict(lines=12,total_lines=12) for p in review.PATHS}
        return config, state, task, decision, suite, reads

    def test_exact_independent_review_role_and_publication(self):
        parent, state, config, settings = self.fixture()
        review.qualify(config, parent, state, settings)
        for key, value in (('head_sha','b'*40),('manifest_sha256','b'*64),('reviewer','author')):
            with self.assertRaises(ValueError):
                review.qualify(dict(config, **{key:value}), parent, state, settings)
        with self.assertRaises(ValueError):
            review.qualify(config, parent, state, dict(agents={review.REVIEWER:'planning'}))

    def test_ci_or_parent_review_drift_is_not_approved(self):
        parent, state, config, settings = self.fixture()
        for key, value in (('coverage_ci','failure'),('merge_authorized',True),('predecessor_merged_sha','b'*40)):
            changed=copy.deepcopy(state);changed['publication'][key]=value
            with self.assertRaises(ValueError):review.qualify(config,parent,changed,settings)
        with self.assertRaises(ValueError):review.qualify(config,parent,dict(state,receipt={'task':'stale'}),settings)

    def test_receipt_binds_exact_sha_without_feature_red_or_release_authority(self):
        result=review.receipt(*self.evidence(),'source')
        self.assertEqual(result['head_sha'],review.HEAD)
        self.assertTrue(result['delivery_approval'])
        for key in ('historical_tdd_red','product_admission_authorized','merge_authorized','deploy_authorized'):
            self.assertFalse(result[key])

    def test_wrong_task_wake_source_and_stale_manifest_are_rejected(self):
        for index, key, value in ((2,'status','failed'),(2,'wakeup_id','other'),
                (3,'status','changes_requested'),(3,'source_task_id','other'),
                (4,'manifest_sha256','b'*64),(4,'review_task','other'),(4,'tests',255),
                (4,'network','bridge'),(4,'snapshot_mount','rw'),(4,'exit_code',1)):
            args=list(self.evidence());args[index]=dict(args[index],**{key:value})
            with self.assertRaises(ValueError):review.receipt(*args,'source')

    def test_incomplete_reads_do_not_approve(self):
        args=list(self.evidence());args[5][review.PATHS[0]]['lines']=11
        with self.assertRaises(ValueError):review.receipt(*args,'source')

    def test_read_recovery_requires_specific_blocker_and_real_complete_canary(self):
        config,state,task,_,suite,reads=self.evidence()
        state.update(stage='blocked',reason='complete delivery reads required')
        reads.pop(review.PATHS[0])
        canary=dict(schema='u3-review-read-canary-v1',status='passed',model_calls=0,
            complete_reads={p:dict(lines=10,total_lines=10) for p in review.PATHS},
            files_sha256={p:'f'*64 for p in review.PATHS},pages=16,large_pages=4,
            early_suite_denied=True,inputs_unchanged=True,network='none',delivery_approval=False)
        result=review.read_recovery_evidence(config,state,task,['APPROVE'],suite,reads,canary)
        self.assertFalse(result['delivery_approval'])
        self.assertEqual(result['failed_task'],'task')
        for changed in (dict(model_calls=1),dict(network='bridge'),dict(early_suite_denied=False),
                        dict(complete_reads={}),dict(delivery_approval=True)):
            with self.assertRaises(ValueError):
                review.read_recovery_evidence(config,state,task,['APPROVE'],suite,reads,dict(canary,**changed))
        for changed in (dict(read_recovery={}),dict(reason='functional regression')):
            with self.assertRaises(ValueError):
                review.read_recovery_evidence(config,dict(state,**changed),task,['APPROVE'],suite,reads,canary)

    def test_read_contract_joins_actual_grant_schema_and_rejects_old_wakeup(self):
        import sqlite3
        import tempfile
        from pathlib import Path
        from contextlib import contextmanager
        con=sqlite3.connect(':memory:');con.row_factory=sqlite3.Row
        self.addCleanup(con.close)
        con.execute('CREATE TABLE native_bindings(request_id TEXT,task_id TEXT,agent_id TEXT,scope TEXT,issue_id TEXT)')
        con.execute('CREATE TABLE grants(request_id TEXT,mode TEXT)')
        con.execute('INSERT INTO native_bindings VALUES(?,?,?,?,?)',('request','task',review.REVIEWER,'scope','child'))
        con.execute('INSERT INTO grants VALUES(?,?)',('request','review'))
        @contextmanager
        def db():yield con
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp,'native.json').write_text('{}')
            b=SimpleNamespace(db=db,STATE=Path(tmp))
            with patch.object(review,'saved',return_value=({'issue_id':'child','reviewer':review.REVIEWER},
                    dict(stage='awaiting_review',wakeup_id='wake'))),\
                    patch.object(review.native,'task_record',return_value=dict(issue_id='child',wakeup_id='wake')) as task:
                self.assertEqual(review.read_contract(b,'request'),list(review.PATHS))
                self.assertIsNone(review.read_contract(b,'unrelated'))
                task.return_value=dict(issue_id='child',wakeup_id='old')
                with self.assertRaisesRegex(ValueError,'binding required'):review.read_contract(b,'request')

    def test_no_registration_has_no_validation_or_dispatch_authority(self):
        with patch.object(review,'saved',return_value=None),patch.object(review,'current') as current:
            self.assertIsNone(review.validate(None,'volume','source'))
            review.tick(None);current.assert_not_called()

    def test_terminal_state_does_not_repeat_dispatch(self):
        with patch.object(review,'saved',return_value=({},dict(stage='blocked'))),\
                patch.object(review,'current') as current:
            review.tick(None);review.tick(None);current.assert_not_called()
        with patch.object(review,'saved',return_value=({},dict(stage='delivery_review_approved'))),\
                patch.object(review,'current') as current:
            review.tick(None);current.assert_not_called()

    def test_initial_wakeup_uses_review_mode_only(self):
        with patch.object(review.native,'_ensure_initial_start') as start:
            review.native.ensure_review_start({},'issue','agent','source','a'*64,'note')
            self.assertEqual(start.call_args.kwargs['expected_mode'],'review')
            self.assertEqual(start.call_args.kwargs['prefix'],'DELIVERY_REVIEW_START')

    def suite_fixture(self):
        _,_,config,_=self.fixture()
        parent=dict(intake=dict(seed=dict(task_id='source',snapshot=dict(volume='volume')),
            base=dict(volume='base',issue_id='original',manifest_sha256='b'*64),proof=dict(actual=261)))
        b=SimpleNamespace(OWNER='owner',PREFIX='project',docker=Mock(side_effect=[
            dict(Labels={'delivery-kit.owner':'owner','delivery-kit.issue-id':'original'}),dict(Image='sha256:'+'c'*64)]))
        return config,parent,b

    def test_fixed_suite_only_matches_registered_source_and_retains_no_red(self):
        config,parent,b=self.suite_fixture()
        with patch.object(review,'saved',return_value=(config,dict(stage='awaiting_review'))),\
                patch.object(review.integration,'saved',return_value=(parent,{})),\
                patch.object(review,'current',return_value=(parent,None,None)),\
                patch.object(review.controls,'owned',return_value=dict(Type='volume',Source='volume',ReadOnly=True)),\
                patch.object(review,'job_request',return_value='request'),\
                patch.object(jobs,'run',return_value=dict(proof=parent['intake']['proof'],output='proof',
                    image='sha256:'+'c'*64,output_sha256='d'*64,job_key='request',contract_sha256='e'*64)) as job:
            self.assertIsNone(review.validate(b,'other','source'))
            job.assert_not_called()
            result=review.validate(b,'volume','source',suite_evidence=True)
            self.assertEqual(result['tests'],261)
            self.assertFalse(result['historical_tdd_red'])
            self.assertNotIn('checkpoint_evidence',result)
            self.assertEqual(result['suite']['test_command'],['python','/u3_product_probe.py'])
            job.assert_called_once_with(b,'request',parent['intake']['base'],parent['intake']['seed'],parent['intake']['proof'])
            self.assertEqual(result['suite']['validation_job_key'],'request')

    def test_suite_drift_and_unadmitted_stage_are_rejected(self):
        config,parent,b=self.suite_fixture()
        with patch.object(review,'saved',return_value=(config,dict(stage='awaiting_review'))),\
                patch.object(review.integration,'saved',return_value=(parent,{})),\
                patch.object(review,'current',return_value=(parent,None,None)),\
                patch.object(review.controls,'owned',return_value=dict(ReadOnly=True)),\
                patch.object(review,'job_request',return_value='request'),\
                patch.object(jobs,'run',return_value=dict(proof=dict(actual=260))):
            with self.assertRaisesRegex(ValueError,'suite or snapshot drift'):
                review.validate(b,'volume','source',suite_evidence=True)
        with patch.object(review,'saved',return_value=(config,dict(stage='awaiting_budget'))),\
                patch.object(review.integration,'saved',return_value=(parent,{})):
            with self.assertRaisesRegex(ValueError,'no active final review'):
                review.validate(b,'volume','source')

    def test_child_binding_only_accepts_exact_review_agent_wake_and_snapshot(self):
        config,parent,b=self.suite_fixture();b.assign_review=Mock()
        binding=dict(issue_id='child',mode='review',agent_id=review.REVIEWER,wakeup_id='wake')
        with patch.object(review,'saved',return_value=(config,dict(stage='awaiting_review',wakeup_id='wake'))),\
                patch.object(review,'current',return_value=(parent,None,None)),\
                patch.object(review.controls,'owned'):
            self.assertTrue(review.authorize_binding(b,binding))
            b.assign_review.assert_called_once_with(dict(source_task_id='source',review_agent_id=review.REVIEWER))
            for key,value in (('mode','implementation'),('agent_id','author'),('wakeup_id','other')):
                with self.assertRaises(ValueError):review.authorize_binding(b,dict(binding,**{key:value}))
            self.assertFalse(review.authorize_binding(b,dict(binding,issue_id='other')))

    def test_consumed_wakeup_exposes_pre_session_failure_without_new_dispatch(self):
        _,_,config,settings=self.fixture();settings.update(token='test',workspace_id='workspace')
        state=dict(wakeup_id='wake');task=dict(id='failed',issue_id='child',wakeup_id='wake',status='failed')
        wake=dict(id='wake',agent_id=review.REVIEWER,last_task_id='failed')
        with patch.object(review.native,'issue_task_runs',return_value=[]),\
                patch.object(review.urllib.request,'urlopen',return_value=io.BytesIO(json.dumps([wake]).encode())),\
                patch.object(review.native,'task_record',return_value=task):
            self.assertEqual(review.tasks_for_wake(settings,config,state),[task])

    def test_consumed_wakeup_cannot_promote_an_unrelated_task(self):
        _,_,config,settings=self.fixture();settings.update(token='test',workspace_id='workspace')
        wake=dict(id='wake',agent_id=review.REVIEWER,last_task_id='other')
        with patch.object(review.native,'issue_task_runs',return_value=[]),\
                patch.object(review.urllib.request,'urlopen',return_value=io.BytesIO(json.dumps([wake]).encode())),\
                patch.object(review.native,'task_record',return_value=dict(id='other',issue_id='wrong',wakeup_id='wake')):
            with self.assertRaisesRegex(ValueError,'ownership drift'):
                review.tasks_for_wake(settings,config,dict(wakeup_id='wake'))

    def recovery_fixture(self):
        _,_,config,_=self.fixture();state=dict(stage='blocked',wakeup_id='failed-wake')
        task=dict(id='failed-review',status='completed',agent_id=review.REVIEWER,issue_id='child',wakeup_id='failed-wake')
        rpc=dict(status='failed',receipt=json.dumps(dict(error_type='DockerOperationTimeout')))
        probe=dict(schema='u3-durable-review-canary-v1',head_sha=review.HEAD,manifest_sha256='a'*64,
            model_calls=0,creates=1,starts=1,delivery_approval=False,job_receipt=dict(
                schema='durable-coverage-job-receipt-v1',job_key='d'*64,proof=dict(actual=261),
                recovered_events=['start_response_timeout'],network='none',snapshot_mount='readonly'))
        return config,state,task,['REQUEST_CHANGES'],rpc,probe,dict(actual=261)

    def test_infrastructure_recovery_requires_actual_failed_review_and_new_durable_canary(self):
        evidence=self.recovery_fixture()
        result=review.recovery_evidence(*evidence)
        self.assertFalse(result['delivery_approval'])
        self.assertEqual(result['failed_task'],'failed-review')
        for index,key,value in ((1,'stage','awaiting_review'),(2,'wakeup_id','other'),
                (4,'status','passed'),(5,'creates',2),(5,'head_sha','b'*40),
                (5,'delivery_approval',True),(5,'model_calls',1)):
            args=list(self.recovery_fixture());args[index]=dict(args[index],**{key:value})
            with self.assertRaises(ValueError):review.recovery_evidence(*args)

    def test_functional_change_request_or_already_consumed_recovery_cannot_be_replayed(self):
        args=list(self.recovery_fixture());args[4]['receipt']=json.dumps(dict(error_type='ValueError'))
        with self.assertRaises(ValueError):review.recovery_evidence(*args)
        args=list(self.recovery_fixture());args[1]['infrastructure_recovery']={}
        with self.assertRaises(ValueError):review.recovery_evidence(*args)
