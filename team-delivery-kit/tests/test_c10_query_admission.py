import copy
import hashlib
import unittest
from broker import c10_query_admission as query,c10_checkpoint_contract as gates,c10_syntax_recovery as syntax


class C10QueryAdmissionTests(unittest.TestCase):
    def setUp(self):
        facts={'test_sha256':'a'*64,'manifest_sha256':'b'*64,'bytes':30114,
            'source_changed':True,'python_syntax_valid':True,'node_syntax_valid':True,
            'test_methods_preserved':True,'non_driver_ast_preserved':True}
        seed={'task_id':'seed-author','snapshot':{'volume':'seed'},'validation':facts,'checkpoint':2}
        proof={'worker_image':'sha256:'+'d'*64,'schema':'surgical-driver-registry-probe-v3',
            'status':'passed','network':'none','uid':10000,'delivery_approval':False}
        for flag in syntax.FLAGS:proof[flag]=True
        self.config={'author':'author','cto':'cto'}
        self.state={'issue_id':'issue','stage':'blocked','category':'c10_decomposition_semantic_contradiction',
            'author_task':'seed-author','snapshot':seed['snapshot'],'validation':facts,
            'functional_diagnosis':{'snapshot':seed['snapshot'],'validation':facts},
            'functional_diagnosis_receipt':{'obsolete':True},
            'functional_correction':{'old_scope':True},'functional_fragment_recovery':{'old_scope':True},
            'c10_decomposition':{'current_seed':seed,'author_scope_authorized':False,
                'checkpoint_contract_available':{'schema':gates.SCHEMA,'contract_sha256':'c'*64,'phase_author_capability_installed':True}},
            'staged':{'current':2,'driver_guard':{'qualification':proof,'worker_image':proof['worker_image']}}}
        self.report={'classification':'DRIVER_OBSERVATION','certificate':{'task_id':'cto-task','snapshot':'seed',
            'test_sha256':'a'*64,'decision_sha256':'e'*64},'decision':{'action':'request_test_revision','optional_files':[],
            'reason':'DRIVER_OBSERVATION: QUERY only: wrap bare arrays at tests/test_incremental_u3.py lines 512/515/528/531 as items envelopes. STATUS remains blocked. All259 tests must show only status_genA_urls missing: PARTIAL, not Green.'}}
        import json
        self.report['certificate']['decision_sha256']=hashlib.sha256(json.dumps(self.report['decision'],sort_keys=True).encode()).hexdigest()

    def approved(self):
        state=query.prepare_intake(self.state)
        state.update(stage='blocked',category='maintenance_diagnosis_driver_observation',functional_diagnosis_receipt=self.report)
        return query.prepare_authorization(self.config,state,48)

    def test_intake_archives_bad_decision_and_is_once_readonly(self):
        revised=query.prepare_intake(self.state)
        self.assertEqual(revised['c10_query_intake']['prior_receipt'],{'obsolete':True})
        self.assertNotIn('functional_diagnosis_receipt',revised)
        self.assertFalse(revised['c10_query_intake']['author_scope_authorized'])
        self.assertIn('QUERY ONLY',revised['functional_diagnosis']['note'])
        self.assertLess(len(revised['functional_diagnosis']['note']),3000)
        with self.assertRaises(ValueError):query.prepare_intake(revised)

    def test_new_query_scope_preserves_consumed_scopes_without_authorizing_status(self):
        revised=query.prepare_authorization(self.config,dict(query.prepare_intake(self.state),
            stage='blocked',category='maintenance_diagnosis_driver_observation',functional_diagnosis_receipt=self.report),48)
        cp=revised['c10_checkpoints']
        self.assertEqual(cp['phase'],'QUERY');self.assertTrue(cp['author_scope_authorized'])
        self.assertFalse(cp['status_scope_authorized']);self.assertEqual(cp['attempt_limit'],1)
        self.assertEqual(cp['prior']['functional_correction'],{'old_scope':True})
        self.assertNotIn('functional_correction',revised);self.assertNotIn('functional_fragment_recovery',revised)
        self.assertFalse(revised['delivery_approval'])
        with self.assertRaises(ValueError):query.prepare_authorization(self.config,revised,48)

    def test_missing_phase_authority_stale_seed_and_budget_are_rejected(self):
        state=query.prepare_intake(self.state)
        state.update(stage='blocked',category='maintenance_diagnosis_driver_observation',functional_diagnosis_receipt=self.report)
        for change in ('budget','stale','badclassification','incomplete','selfreview','qualifiedworker'):
            candidate=copy.deepcopy(state);config=copy.deepcopy(self.config);remaining=48
            if change=='budget':remaining=47
            if change=='stale':candidate['functional_diagnosis_receipt']['certificate']['test_sha256']='f'*64
            if change=='badclassification':candidate['functional_diagnosis_receipt']['classification']='UNRESOLVED'
            if change=='incomplete':candidate['functional_diagnosis_receipt']['decision']['reason']='DRIVER_OBSERVATION: QUERY already works'
            if change=='selfreview':config['cto']=config['author']
            if change=='qualifiedworker':candidate['staged']['driver_guard']['qualification']['direct_handler_fenced']=False
            with self.assertRaises(ValueError):query.prepare_authorization(config,candidate,remaining)

    def test_exact_new_wakeup_note_and_hash_select_query_only(self):
        state=self.approved();state.update(stage='awaiting_author',wakeup_id='new-wake')
        note=query.author_note(state)
        task={'id':'new-author','agent_id':'author','issue_id':'issue','wakeup_id':'new-wake','handoff_note':note}
        grant=query.select(self.config,state,task)
        self.assertEqual(grant['surgical']['expected_sha256'],'a'*64)
        self.assertEqual(grant['surgical']['protocol'],'typed_driver_lines_v4')
        self.assertLess(len(note),3000)
        for changed in (dict(task,wakeup_id='old-wake'),dict(task,handoff_note='old note'),dict(task,issue_id='other')):
            with self.assertRaises(ValueError):query.select(self.config,state,changed)
        with self.assertRaises(ValueError):query.select(self.config,dict(state,stage='blocked'),task)
        from broker import driver_checkpoint_policy as policy
        self.assertEqual(policy.select(self.config,state,'issue',task),grant)
        changed=copy.deepcopy(state);changed['c10_checkpoints']['scope_id']='oldscope'
        with self.assertRaises(ValueError):query.select(self.config,changed,task)
        changed=copy.deepcopy(state)
        changed['c10_checkpoints']['qualification']['direct_handler_fenced']=False
        changed['staged']['driver_guard']['qualification']['direct_handler_fenced']=False
        with self.assertRaises(ValueError):query.select(self.config,changed,task)

    def test_current_native_context_uses_new_query_note_not_legacy_status(self):
        import sqlite3,json
        from contextlib import closing
        from broker import harness_repair_task as h
        state=self.approved();state.update(stage='awaiting_author',wakeup_id='new-wake')
        task={'id':'new-author','agent_id':'author','issue_id':'issue','wakeup_id':'new-wake',
            'handoff_note':query.author_note(state)}
        with closing(sqlite3.connect(':memory:')) as con:
            con.execute('CREATE TABLE harness_repair_tasks(config TEXT,state TEXT)')
            con.execute('INSERT INTO harness_repair_tasks VALUES (?,?)',(json.dumps(self.config),json.dumps(state)))
            context=h.current_maintenance_context(con,{'id':'issue'},task)
        self.assertIn('QUERY-ONLY',context['handoff_note'])
        self.assertNotIn('obsolete STATUS plan',context['handoff_note'])

    def test_seed_binding_cannot_reuse_a_different_phase_or_snapshot(self):
        state=self.approved();seed=state['c10_checkpoints']['seed']
        self.assertTrue(query.seed_binding(state,seed))
        with self.assertRaises(ValueError):query.seed_binding(state,dict(seed,snapshot={'volume':'old'}))
        state['c10_checkpoints']['phase']='STATUS'
        with self.assertRaises(ValueError):query.seed_binding(state,seed)

    def recovery_fixture(self):
        import json
        state=self.approved();state.update(stage='blocked',category='c10_checkpoint_validation_failed',
            author_task='query-author',snapshot={'volume':'query'},
            validation=dict(self.state['validation'],test_sha256='f'*64,manifest_sha256='0'*64))
        state['c10_checkpoints']['scope_receipt']={'schema':gates.SCHEMA,'phase':'QUERY','scope_verified':True,
            'seed_test_sha256':'a'*64,'test_sha256':'f'*64,'manifest_sha256':'0'*64,'delivery_approval':False}
        stored={'task_id':'query-author','status':'failed','manifest_sha256':'0'*64,
            'receipt':json.dumps({'error_type':'ValueError','failure':None})}
        return state,stored

    def test_structural_validation_recovery_preserves_failed_run_and_never_restarts_author(self):
        state,stored=self.recovery_fixture();revised=query.prepare_suite_recovery(state,stored)
        self.assertEqual(revised['stage'],'maintenance_suite_pending')
        self.assertEqual(revised['c10_query_validation_recovery']['prior_run'],stored)
        self.assertFalse(revised['c10_query_validation_recovery']['retry_authorized'])
        self.assertEqual(revised['author_task'],'query-author')
        with self.assertRaises(ValueError):query.prepare_suite_recovery(revised,stored)

    def test_recovery_refuses_functional_failures_stale_receipts_or_scope_drift(self):
        import json
        state,stored=self.recovery_fixture()
        for mutation in ('functional','stale','scope','phase'):
            current=copy.deepcopy(state);run=copy.deepcopy(stored)
            if mutation=='functional':run['receipt']=json.dumps({'failure':{'category':'executed_test_failure'}})
            if mutation=='stale':run['task_id']='old'
            if mutation=='scope':current['c10_checkpoints']['scope_receipt']['test_sha256']='bad'
            if mutation=='phase':current['c10_checkpoints']['phase']='STATUS'
            with self.assertRaises(ValueError):query.prepare_suite_recovery(current,run)
