import copy
import unittest
from broker.driver_checkpoint_policy import select


class DriverCheckpointPolicyTests(unittest.TestCase):
    def setUp(self):
        image = 'sha256:' + 'd' * 64
        proof = dict(schema='surgical-driver-registry-probe-v3', status='passed', network='none',
            uid=10000, worker_image=image, delivery_approval=False)
        for key in ('actual_registry', 'actual_default_selection', 'actual_acp_selection',
                'readless_edit_denied', 'generic_write_and_terminal_denied', 'direct_handler_fenced',
                'invalid_syntax_preserves_bytes', 'outside_driver_change_preserves_bytes',
                'test_weakening_preserves_bytes', 'stale_edit_denied', 'fixed_node_check', 'credentials_absent'):
            proof[key] = True
        self.config = {'author':'author', 'file_sha256':{'tests/test_incremental_u3.py':'a'*64}}
        self.state = {'issue_id':'child', 'stage':'awaiting_author', 'wakeup_id':'wake',
            'staged':{'current':1, 'history':[], 'driver_guard':{'qualification':proof, 'worker_image':image}}}
        self.task = {'id':'task', 'issue_id':'child', 'agent_id':'author', 'wakeup_id':'wake'}

    def test_exact_opt_in_selects_only_qualified_image_and_original_hash(self):
        result = select(self.config,self.state,'child',self.task)
        self.assertEqual(result['surgical']['protocol'],'typed_driver_v3')
        self.assertEqual(result['surgical']['expected_sha256'],'a'*64)
        self.assertEqual(result['worker_image'],self.state['staged']['driver_guard']['worker_image'])

    def test_line_protocol_needs_separate_registry_qualification(self):
        guard=self.state['staged']['driver_guard'];guard['line_ranges']=True
        with self.assertRaises(ValueError):select(self.config,self.state,'child',self.task)
        guard['qualification']['line_range_registry_qualified']=True
        self.assertEqual(select(self.config,self.state,'child',self.task)['surgical']['protocol'],'typed_driver_lines_v4')

    def test_decomposition_cannot_reuse_consumed_legacy_capability(self):
        self.state['c10_decomposition']={'author_scope_authorized':False}
        with self.assertRaisesRegex(ValueError,'phase-specific author capability'):
            select(self.config,self.state,'child',self.task)

    def test_unrelated_or_unarmed_tasks_keep_default_worker(self):
        self.assertIsNone(select(self.config,self.state,'other',self.task))
        self.assertIsNone(select(self.config,self.state,'child',dict(self.task,agent_id='reviewer')))
        state = copy.deepcopy(self.state);state['staged'].pop('driver_guard')
        self.assertIsNone(select(self.config,state,'child',self.task))

    def test_stale_wakeup_and_blocked_author_fail_closed(self):
        with self.assertRaises(ValueError):select(self.config,self.state,'child',dict(self.task,wakeup_id='stale'))
        with self.assertRaises(ValueError):select(self.config,dict(self.state,stage='blocked'),'child',self.task)

    def test_native_prompt_binding_task_id_is_accepted_without_relaxing_identity(self):
        binding=dict(self.task);binding['task_id']=binding.pop('id')
        self.assertEqual(select(self.config,self.state,'child',binding)['surgical']['protocol'],'typed_driver_v3')
        with self.assertRaises(ValueError):select(self.config,self.state,'child',dict(binding,id='different'))

    def test_checkpoint_native_scope_is_fresh_but_ordinary_corrections_are_persistent(self):
        from unittest.mock import patch
        from broker import native
        task_id='00000000-0000-4000-8000-000000000001'
        issue='00000000-0000-4000-8000-000000000002'
        agent='00000000-0000-4000-8000-000000000003'
        task=dict(id=task_id,issue_id=issue,status='running',wakeup_id='wake',handoff_note='normal')
        settings={'workspace_id':'workspace','agents':{agent:'implementation'}}
        with patch.object(native,'task_record',return_value=task):
            self.assertTrue(native.task_binding(settings,task_id,agent)['scope'].endswith(issue))
            task['handoff_note']='Source: origin\nDELIVERY_DRIVER_CHECKPOINT_V3\n'
            self.assertTrue(native.task_binding(settings,task_id,agent)['scope'].endswith(task_id))

    def test_tampered_qualification_and_mutable_image_rejected(self):
        for key in ('worker_image','actual_registry','uid','delivery_approval','network'):
            state = copy.deepcopy(self.state)
            state['staged']['driver_guard']['qualification'][key] = 'invalid'
            with self.assertRaises(ValueError):select(self.config,state,'child',self.task)

    def test_c10_requires_exact_prior_checkpoint_and_hash(self):
        state = copy.deepcopy(self.state);state['staged']['current']=2
        with self.assertRaises(ValueError):select(self.config,state,'child',self.task)
        facts = dict(source_changed=True,python_syntax_valid=True,node_syntax_valid=True,
            test_methods_preserved=True,non_driver_ast_preserved=True,bytes=31684,
            manifest_sha256='b'*64,test_sha256='c'*64)
        state['staged']['history']=[{'checkpoint':1,'validation':facts}]
        self.assertEqual(select(self.config,state,'child',self.task)['surgical']['expected_sha256'],'c'*64)
        facts['node_syntax_valid']=False
        with self.assertRaises(ValueError):select(self.config,state,'child',self.task)

    def test_functional_correction_uses_current_seed_and_requires_exact_certificate(self):
        state=copy.deepcopy(self.state);state['staged']['current']=2
        facts=dict(source_changed=True,python_syntax_valid=True,node_syntax_valid=True,
            test_methods_preserved=True,non_driver_ast_preserved=True,bytes=32057,
            manifest_sha256='b'*64,test_sha256='c'*64)
        state['staged']['history']=[{'checkpoint':1,'validation':dict(facts,test_sha256='a'*64)}]
        seed={'checkpoint':2,'validation':facts,'snapshot':{'volume':'current'}}
        state['functional_diagnosis']={'snapshot':seed['snapshot'],'validation':facts}
        state['functional_correction']={'seed':seed,'certificate':{'task_id':'cto'},'attempt_limit':1}
        state['functional_diagnosis_receipt']={'certificate':{'task_id':'cto'},'classification':'DRIVER_OBSERVATION'}
        self.assertEqual(select(self.config,state,'child',self.task)['surgical']['expected_sha256'],'c'*64)
        original=copy.deepcopy(state['functional_correction']['seed'])
        next_seed=dict(original,task_id='part1',snapshot={'volume':'part1'},validation=dict(facts,test_sha256='f'*64))
        failure={'category':'executed_test_failure','tests_executed':259,'source_task':'part1','volume':'part1',
            'exception_types':['AssertionError'],'missing_metadata_keys':[],
            'failures':[{'kind':'FAIL','test':'test_c10_stale_query_and_status_responses_are_discarded'}]}
        state['functional_fragment_recovery']={'current':2,'original_seed':original,'attempt_limit_per_fragment':1,
            'history':[{'seed':next_seed,'failure':failure}]}
        self.assertEqual(select(self.config,state,'child',self.task)['surgical']['expected_sha256'],'f'*64)
        state['functional_correction']['certificate']={'task_id':'stale'}
        with self.assertRaises(ValueError):select(self.config,state,'child',self.task)
