import copy
import hashlib
import json
import unittest
from broker import c10_status_admission as status,c10_checkpoint_contract as gates
import test_c10_query_admission as query_tests
import test_c10_checkpoint_contract as contract_tests


class C10StatusAdmissionTests(unittest.TestCase):
    def setUp(self):
        query=query_tests.C10QueryAdmissionTests();query.setUp()
        fixture=contract_tests.C10CheckpointContractTests();fixture.setUp()
        self.config=query.config
        self.state=query.approved()
        facts=dict(self.state['validation'],test_sha256=gates.sha(fixture.query),manifest_sha256='a'*64)
        self.state.update(stage='blocked',category='c10_query_partial_requires_status_admission',
            author_task='query-author',snapshot={'volume':'query'},validation=facts)
        self.state['c10_checkpoints']['scope_receipt']=dict(fixture.scope)
        self.state['c10_checkpoints']['seed']['validation']['test_sha256']=gates.sha(fixture.seed)
        self.output=fixture.output
        from broker import suite_failure
        failure=suite_failure.evidence(1,self.output,'query-author','query')
        self.state['c10_checkpoints']['query_receipt']=gates.partial_receipt(self.state,failure,self.output)
        decision={'action':'request_test_revision','optional_files':[],
            'reason':'DRIVER_OBSERVATION: STATUS tests/test_incremental_u3.py 534-536 only; click filter-open then filter-completed, capture status_genA_urls/status_genB_urls from pending requests, resolve CURRENT COMPLETED then STALE OPEN with items, flush and measure pending_left=pending.length. QUERY frozen. Full259 Green then independent review.'}
        self.report={'classification':'DRIVER_OBSERVATION','decision':decision,
            'certificate':{'task_id':'status-cto','snapshot':'query','test_sha256':facts['test_sha256'],
                'decision_sha256':hashlib.sha256(json.dumps(decision,sort_keys=True).encode()).hexdigest()}}

    def authorized(self):
        revised=status.prepare_intake(self.state,self.output)
        revised.update(stage='blocked',category='maintenance_diagnosis_driver_observation',functional_diagnosis_receipt=self.report)
        return status.prepare_authorization(self.config,revised,48)

    def test_intake_requires_real_partial_and_preserves_prior_authority(self):
        revised=status.prepare_intake(self.state,self.output)
        self.assertEqual(revised['c10_status_intake']['seed']['task_id'],'query-author')
        self.assertEqual(revised['c10_checkpoints'],self.state['c10_checkpoints'])
        self.assertFalse(revised['c10_status_intake']['author_scope_authorized'])
        self.assertIn('534-536',revised['functional_diagnosis']['note'])
        with self.assertRaises(ValueError):status.prepare_intake(revised,self.output)
        with self.assertRaises(ValueError):status.prepare_intake(self.state,self.output.replace('259','258'))
        stale=copy.deepcopy(self.state);stale['c10_checkpoints']['query_receipt']['validation']['test_sha256']='bad'
        with self.assertRaises(ValueError):status.prepare_intake(stale,self.output)

    def test_distinct_status_scope_keeps_query_receipt_without_approval(self):
        revised=self.authorized();cp=revised['c10_checkpoints']
        self.assertEqual(cp['phase'],'STATUS');self.assertEqual(cp['attempt_limit'],1)
        self.assertTrue(cp['status_scope_authorized']);self.assertFalse(cp['delivery_approval'])
        self.assertEqual(cp['query_receipt'],self.state['c10_checkpoints']['query_receipt'])
        self.assertEqual(cp['prior_query'],self.state['c10_checkpoints'])
        self.assertNotEqual(cp['scope_id'],cp['prior_query']['scope_id'])
        with self.assertRaises(ValueError):status.prepare_authorization(self.config,revised,48)

    def test_no_old_cto_self_review_wrong_scope_or_low_budget(self):
        revised=status.prepare_intake(self.state,self.output)
        revised.update(stage='blocked',category='maintenance_diagnosis_driver_observation',functional_diagnosis_receipt=self.report)
        for mutation in ('budget','old','scope','classification','worker','self'):
            state=copy.deepcopy(revised);config=dict(self.config);remaining=48
            if mutation=='budget':remaining=47
            if mutation=='old':state['functional_diagnosis_receipt']['certificate']['task_id']=state['c10_checkpoints']['authority']['certificate']['task_id']
            if mutation=='scope':state['functional_diagnosis_receipt']['decision']['reason']='DRIVER_OBSERVATION: repair QUERY and STATUS'
            if mutation=='classification':state['functional_diagnosis_receipt']['classification']='UNRESOLVED'
            if mutation=='worker':state['staged']['driver_guard']['qualification']['direct_handler_fenced']=False
            if mutation=='self':config['cto']=config['author']
            with self.assertRaises(ValueError):status.prepare_authorization(config,state,remaining)

    def test_policy_and_context_select_status_not_query_or_legacy(self):
        state=self.authorized();state.update(stage='awaiting_author',wakeup_id='status-wake')
        task={'id':'status-author','agent_id':'author','issue_id':'issue','wakeup_id':'status-wake','handoff_note':status.author_note(state)}
        from broker import driver_checkpoint_policy as policy,harness_repair_task as h
        grant=policy.select(self.config,state,'issue',task)
        self.assertEqual(grant['surgical']['expected_sha256'],state['validation']['test_sha256'])
        self.assertTrue(status.seed_binding(state,state['c10_checkpoints']['seed']))
        import sqlite3
        from contextlib import closing
        with closing(sqlite3.connect(':memory:')) as con:
            con.execute('CREATE TABLE harness_repair_tasks(config TEXT,state TEXT)')
            con.execute('INSERT INTO harness_repair_tasks VALUES (?,?)',(json.dumps(self.config),json.dumps(state)))
            context=h.current_maintenance_context(con,{'id':'issue'},task)
        self.assertIn('STATUS-ONLY',context['handoff_note']);self.assertNotIn('QUERY-ONLY',context['handoff_note'])
        for changed in (dict(task,wakeup_id='query-wake'),dict(task,handoff_note='old note')):
            with self.assertRaises(ValueError):status.select(self.config,state,changed)
        bad=copy.deepcopy(state);bad['c10_checkpoints']['phase']='OTHER'
        with self.assertRaises(ValueError):policy.select(self.config,bad,'issue',task)

    def test_seed_binding_rejects_stale_partial_code_and_cross_phase(self):
        state=self.authorized();receipt=state['c10_checkpoints']['seed']
        for mutation in ('seed','partial','code','phase'):
            bad=copy.deepcopy(state);seed=copy.deepcopy(receipt)
            if mutation=='seed':seed['task_id']='old'
            if mutation=='partial':bad['c10_checkpoints']['query_receipt']['green']=True
            if mutation=='code':bad['c10_checkpoints']['admission_code_sha256']='old'
            if mutation=='phase':bad['c10_checkpoints']['phase']='QUERY'
            with self.assertRaises(ValueError):status.seed_binding(bad,seed)

    def test_atomic_recovery_archives_failed_scope_and_uses_new_qualified_capability(self):
        state=self.authorized();state.update(stage='blocked',category='c10_checkpoint_acceptance_failed',
            author_task='failed-author',snapshot={'volume':'failed'},validation=dict(state['validation'],test_sha256='f'*64))
        cp=state['c10_checkpoints'];cp['scope_receipt']={'schema':gates.SCHEMA,'phase':'STATUS','scope_verified':True,
            'seed_test_sha256':cp['seed']['validation']['test_sha256'],'test_sha256':'f'*64,
            'manifest_sha256':state['validation']['manifest_sha256'],'delivery_approval':False}
        state['suite_failure']={'task':'failed-author'}
        proof=copy.deepcopy(state['staged']['driver_guard']['qualification']);proof['worker_image']='sha256:'+'9'*64
        proof['atomic_status']={'schema':'surgical-status-atomic-probe-v1','status':'passed',
            'network':'none','uid':10000,'model_calls':0,'delivery_approval':False}
        for flag in status.ATOMIC_FLAGS:proof['atomic_status'][flag]=True
        revised=status.prepare_atomic_recovery(self.config,state,proof,48)
        self.assertEqual(revised['author_task'],'query-author')
        self.assertEqual(revised['c10_status_atomic_recovery']['failed_snapshot'],{'volume':'failed'})
        self.assertNotEqual(revised['c10_checkpoints']['scope_id'],cp['scope_id'])
        revised.update(stage='awaiting_author',wakeup_id='atomic-wake')
        task={'id':'atomic-author','agent_id':'author','issue_id':'issue','wakeup_id':'atomic-wake',
            'handoff_note':status.author_note(revised)}
        grant=status.select(self.config,revised,task)
        self.assertEqual(grant['surgical']['atomic_contract'],'c10-status-observations-v1')
        self.assertEqual(grant['worker_image'],proof['worker_image'])
        self.assertIn('not a limit of three new lines',task['handoff_note'])
        with self.assertRaises(ValueError):status.prepare_atomic_recovery(self.config,revised,proof,48)
        bad=copy.deepcopy(proof);bad['atomic_status']['partial_before_write_denied']=False
        with self.assertRaises(ValueError):status.prepare_atomic_recovery(self.config,state,bad,48)
        with self.assertRaises(ValueError):status.prepare_atomic_recovery(self.config,state,proof,47)

    def test_queue_diagnosis_only_new_actual_failure_never_rearms_author(self):
        state=self.authorized();cp=state['c10_checkpoints'];cp['atomic_contract']='c10-status-observations-v1'
        state.update(stage='blocked',category='c10_checkpoint_acceptance_failed',author_task='atomic-author',
            snapshot={'volume':'atomic'},validation=dict(state['validation'],test_sha256='f'*64))
        cp['scope_receipt']={'schema':gates.SCHEMA,'phase':'STATUS','scope_verified':True,
            'seed_test_sha256':cp['seed']['validation']['test_sha256'],'test_sha256':'f'*64,
            'manifest_sha256':state['validation']['manifest_sha256'],'delivery_approval':False}
        output=('FAIL: '+gates.C10+' (tests.test_incremental_u3.DriverTests)\n'
            'AssertionError: 1 != 0 : every issued request must be resolved by the harness\n'
            'Ran 259 tests in 1.0s\nFAILED (failures=1)\n')
        from broker import suite_failure
        state['suite_failure']=suite_failure.evidence(1,output,'atomic-author','atomic')
        state['suite_failure']['diagnostic_read_files']=['app/static/app.js','app/static/index.html','tests/test_incremental_u3.py']
        revised=status.prepare_queue_diagnosis(state,output)
        self.assertEqual(revised['stage'],'maintenance_functional_diagnosis_dispatch')
        self.assertFalse(revised['c10_status_queue_intake']['author_scope_authorized'])
        self.assertEqual(revised['c10_checkpoints'],cp)
        self.assertIn('Never pending=[]',revised['functional_diagnosis']['note'])
        with self.assertRaises(ValueError):status.prepare_queue_diagnosis(revised,output)
        with self.assertRaises(ValueError):status.prepare_queue_diagnosis(state,output.replace('1 != 0','2 != 0'))
