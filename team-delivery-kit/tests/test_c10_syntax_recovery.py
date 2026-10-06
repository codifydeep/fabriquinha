import copy
import hashlib
import unittest
from broker import c10_syntax_recovery as recovery
from broker import driver_checkpoint_policy as policy


class C10SyntaxRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.config={'author':'author','cto':'cto'}
        facts={'source_changed':True,'python_syntax_valid':True,'node_syntax_valid':True,
            'test_methods_preserved':True,'non_driver_ast_preserved':True,'bytes':30114,
            'test_sha256':'a'*64,'manifest_sha256':'b'*64,'delivery_approval':False}
        seed={'task_id':'c09','snapshot':{'volume':'c09-snapshot'},'validation':facts,'checkpoint':2}
        failure={'tests_executed':259,'category':'executed_test_failure','exception_types':['AssertionError'],
            'missing_metadata_keys':[],'source_task':'c09','volume':'c09-snapshot',
            'failures':[{'kind':'FAIL','test':'test_c10_stale_query_and_status_responses_are_discarded'}]}
        cert={'task_id':'cto-plan','snapshot':'c09-snapshot','test_sha256':'a'*64}
        self.task={'id':'failed-c10','status':'completed','agent_id':'author','issue_id':'maintenance','wakeup_id':'old-wake'}
        args={'path':'/workspace/tests/test_incremental_u3.py','expected_sha256':'a'*64,
            'edits':[{'start_line':534,'end_line':536,'new':'invalid\n'},
                {'start_line':537,'end_line':537,'new':'invalid closure\n'}]}
        self.messages=[]
        for call in ('first','second'):
            self.messages.extend([{'type':'tool_use','tool':'surgical_test_edit','call_id':call,'input':copy.deepcopy(args)},
                {'type':'tool_result','tool':'surgical_test_edit','call_id':call,'output_truncated':False,
                    'output':'surgical_edit_rejected:driver_syntax_invalid:balance_driver_constructs_before_submit'}])
        proposal={'proposal_sha256':recovery.digest(args),'node_valid':False,'node_line':144,
            'c09_prefix_preserved':True,'protected_suffix_preserved':True,'ranges':[[534,536],[537,537]]}
        snapshot={'volume':'failed-snapshot'}
        scope={'current':2,'original_seed':seed,'attempt_limit_per_fragment':1,
            'scope':'response_envelope_c10_reviewed','history':[{'seed':seed,'failure':failure}],
            'diagnostics':{'c09_passed':True}}
        self.state={'stage':'blocked','category':'unchanged_functional_driver','issue_id':'maintenance',
            'author_task':'failed-c10','wakeup_id':'old-wake','snapshot':snapshot,'validation':facts,
            'functional_correction':{'seed':seed,'certificate':cert,'attempt_limit':1},
            'functional_diagnosis_receipt':{'certificate':cert,'classification':'DRIVER_OBSERVATION',
                'decision':{'reason':'DRIVER_OBSERVATION: existing independently reviewed C10 query/status plan'}},
            'functional_diagnosis':{'snapshot':seed['snapshot'],'validation':facts},
            'functional_fragment_recovery':scope,
            'staged':{'current':2,'history':[{'checkpoint':1,'validation':facts}],
                'driver_guard':{'worker_image':'sha256:'+'c'*64,'qualification':{'old':True},'line_ranges':True}},
            'current_execution_result':{'category':'identical_syntax_rejections','task_id':'failed-c10',
                'accepted_edits':0,'files_changed_from_seed':False,'suite_reexecuted':False,'retry_authorized':False},
            'c10_diagnosis':{'seed':seed,'author_scope_authorized':True,'authorized_phase':'C10',
                'c09_evidence':{'c09_status':'passed_in_actual_full_suite'},
                'plan_verification':{'verified':True,'certificate':cert,'snapshot':seed['snapshot'],'validation':facts,
                    'scope':[500,553],'bare_array_response_lines':[512,515,528,531],
                    'real_filter_ids':['filter-open','filter-completed']},
                'author_outcome':{'task_id':'failed-c10','snapshot':snapshot,'validation':facts,'suite_reexecuted':False,
                    'proposal_diagnostic':{'source_sha256':'a'*64,'files_modified':False,
                        'application_executed':False,'delivery_approval':False,'proposals':[proposal,copy.deepcopy(proposal)]}}}}
        self.proof=dict(schema='surgical-driver-registry-probe-v3',status='passed',protocol='typed_driver_lines_v4',
            network='none',uid=10000,model_calls=0,delivery_approval=False,worker_image='sha256:'+'d'*64)
        self.proof.update({key:True for key in recovery.FLAGS})

    def prepare(self,**kwargs):
        return recovery.prepare(kwargs.get('config',self.config),kwargs.get('state',self.state),
            kwargs.get('task',self.task),kwargs.get('messages',self.messages),kwargs.get('proof',self.proof),kwargs.get('remaining',95))

    def test_admits_new_scope_preserves_prior_attempt_and_selects_only_new_worker(self):
        original=copy.deepcopy(self.state)
        revised,seed=self.prepare()
        self.assertEqual(self.state,original)
        receipt=revised['c10_syntax_recovery']
        self.assertEqual(receipt['prior_scope'],original['functional_fragment_recovery'])
        self.assertEqual(receipt['prior_result'],original['current_execution_result'])
        self.assertEqual(receipt['prior_author_outcome'],original['c10_diagnosis']['author_outcome'])
        self.assertEqual(receipt['attempt_limit'],1)
        self.assertFalse(receipt['delivery_approval'])
        self.assertLessEqual(receipt['wrapped_note_characters'],4000)
        self.assertNotIn('current_execution_result',revised)
        self.assertEqual(seed,original['functional_correction']['seed'])
        self.assertEqual(revised['functional_correction'],original['functional_correction'])
        self.assertIn('missing_query_response_ranges',revised['functional_fragment_recovery']['diagnostics'])
        grant=policy.select(self.config,dict(revised,stage='awaiting_author'),'maintenance',self.task)
        self.assertEqual(grant['worker_image'],self.proof['worker_image'])
        self.assertEqual(grant['surgical']['expected_sha256'],'a'*64)
        with self.assertRaises(ValueError):self.prepare(state=revised)

    def test_rejects_old_or_incomplete_qualification_and_insufficient_reserve(self):
        for key in recovery.FLAGS:
            proof=copy.deepcopy(self.proof);proof[key]=False
            with self.subTest(key=key),self.assertRaises(ValueError):self.prepare(proof=proof)
        proof=copy.deepcopy(self.proof);proof['worker_image']='sha256:'+'c'*64
        with self.assertRaises(ValueError):self.prepare(proof=proof)
        for remaining in (47,True):
            with self.assertRaises(ValueError):self.prepare(remaining=remaining)

    def test_changed_snapshot_obsolete_authority_or_fake_results_rejected(self):
        for mutation in ('hash','certificate','scope','query_lines','approved','accepted','suite','output','call','proposal'):
            state=copy.deepcopy(self.state);messages=copy.deepcopy(self.messages)
            if mutation=='hash':state['validation']=dict(state['validation'],test_sha256='f'*64)
            elif mutation=='certificate':state['c10_diagnosis']['plan_verification']['certificate']={'task_id':'other'}
            elif mutation=='scope':state['c10_diagnosis']['plan_verification']['scope']=[430,553]
            elif mutation=='query_lines':state['c10_diagnosis']['plan_verification']['bare_array_response_lines']=[]
            elif mutation=='approved':state['c10_diagnosis']['author_outcome']['proposal_diagnostic']['delivery_approval']=True
            elif mutation=='accepted':state['current_execution_result']['accepted_edits']=1
            elif mutation=='suite':state['current_execution_result']['suite_reexecuted']=True
            elif mutation=='output':messages[1]['output_truncated']=True
            elif mutation=='call':messages[3]['call_id']='unrelated'
            elif mutation=='proposal':messages[2]['input']['edits'][0]['new']='different'
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):self.prepare(state=state,messages=messages)

    def test_grant_denies_contract_or_image_drift_after_admission(self):
        revised,_=self.prepare()
        for mutation in ('scope','note','proof','certificate'):
            state=copy.deepcopy(revised);state['stage']='awaiting_author'
            if mutation=='scope':state['functional_fragment_recovery']['scope']='response_envelope_c10_reviewed'
            elif mutation=='note':state['c10_syntax_recovery']['note_sha256']='0'*64
            elif mutation=='proof':state['staged']['driver_guard']['qualification']['fresh_process_syntax_replay_denied']=False
            elif mutation=='certificate':state['c10_syntax_recovery']['cto_certificate']={'task_id':'other'}
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):policy.select(self.config,state,'maintenance',self.task)

    def test_recovery_identity_and_contract_are_deterministic(self):
        first,_=self.prepare();second,_=self.prepare()
        self.assertEqual(first['c10_syntax_recovery']['scope_id'],second['c10_syntax_recovery']['scope_id'])
        self.assertEqual(first['c10_syntax_recovery']['note_sha256'],second['c10_syntax_recovery']['note_sha256'])
        self.assertNotIn('invalid closure',str(first['c10_syntax_recovery']))
        persisted=copy.deepcopy(first)
        import json
        persisted=json.loads(json.dumps(persisted,sort_keys=True))
        grant=policy.select(self.config,dict(persisted,stage='awaiting_author'),'maintenance',self.task)
        self.assertEqual(grant['worker_image'],self.proof['worker_image'])
        self.assertEqual(first['c10_syntax_recovery']['note_sha256'],
            hashlib.sha256(recovery.delivery.functional_correction_note(persisted).encode()).hexdigest())

    def test_oversized_native_wrapping_rejected_before_state_change(self):
        state=copy.deepcopy(self.state)
        state['functional_diagnosis_receipt']['decision']['reason']='DRIVER_OBSERVATION: '+('x'*1800)
        original=copy.deepcopy(state)
        with self.assertRaisesRegex(ValueError,'bounded wrapped'):self.prepare(state=state)
        self.assertEqual(state,original)

    def bootstrap_fixture(self):
        state,_=self.prepare()
        state.update(stage='blocked',category='maintenance_inspection_failed',error_type='ValueError',
            error_reason='author execution failed',author_task='bootstrap-failed',wakeup_id='bootstrap-wake')
        # Captured old noncanonical / near-limit contract, not a new author scope.
        state['c10_syntax_recovery']['note_sha256']='f'*64
        state['c10_syntax_recovery']['wrapped_note_characters']=3946
        task={'id':'bootstrap-failed','status':'failed','agent_id':'author','issue_id':'maintenance',
            'wakeup_id':'bootstrap-wake','error':'hermes initialize failed: hermes process exited',
            'handoff_note':'x'*4137}
        errors=[{'operation':'worker_submit','category':'bootstrap:broker_internal'}]
        lease={'status':'failed','scenario':'acp-session','request_id':'request','agent_id':'author'}
        return state,task,errors,lease

    def test_zero_tool_bootstrap_failure_has_one_separate_recovery(self):
        state,task,errors,lease=self.bootstrap_fixture();original=copy.deepcopy(state)
        revised,seed=recovery.prepare_bootstrap(self.config,state,task,[],errors,lease,95)
        self.assertEqual(state,original)
        self.assertEqual(revised['c10_syntax_recovery']['scope_id'],state['c10_syntax_recovery']['scope_id'])
        self.assertEqual(revised['c10_bootstrap_recovery']['failed_task'],task['id'])
        self.assertFalse(revised['c10_bootstrap_recovery']['author_tools_executed'])
        self.assertEqual(revised['c10_syntax_recovery']['attempt_limit'],1)
        self.assertEqual(seed,state['functional_correction']['seed'])
        self.assertLessEqual(revised['c10_syntax_recovery']['wrapped_note_characters']+512,4000)
        import json
        persisted=json.loads(json.dumps(revised,sort_keys=True))
        self.assertEqual(policy.select(self.config,dict(persisted,stage='awaiting_author'),'maintenance',task)['worker_image'],self.proof['worker_image'])
        with self.assertRaises(ValueError):recovery.prepare_bootstrap(self.config,revised,task,[],errors,lease,95)

    def test_bootstrap_refuses_tools_other_failure_and_insufficient_reserve(self):
        state,task,errors,lease=self.bootstrap_fixture()
        for mutation in ('tools','running','different_error','binding','budget','seed'):
            s=copy.deepcopy(state);t=copy.deepcopy(task);ls=copy.deepcopy(lease);remaining=95;messages=[]
            if mutation=='tools':messages=[{'type':'tool_use','tool':'read_file'}]
            elif mutation=='running':t['status']='running'
            elif mutation=='different_error':t['error']='iteration budget exhausted'
            elif mutation=='binding':ls['status']='complete'
            elif mutation=='budget':remaining=47
            elif mutation=='seed':s['validation']=dict(s['validation'],test_sha256='e'*64)
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):
                recovery.prepare_bootstrap(self.config,s,t,messages,errors,ls,remaining)

    def decomposition_fixture(self):
        state,_=self.prepare()
        state.update(stage='blocked',category='unchanged_functional_driver')
        args=copy.deepcopy(self.messages[0]['input'])
        args['edits']=[{'start_line':n,'end_line':n if n!=531 else 536,'new':'invalid\n'} for n in (512,515,528,531)]
        messages=[];receipts=[]
        for call,category in (('first','driver_syntax_invalid'),('second','identical_rejected_proposal')):
            output='surgical_edit_rejected:'+category+':change_proposal'
            if call=='first':output+='\nsyntax_category=unexpected_token driver_line=137'
            messages.extend([{'type':'tool_use','tool':'surgical_test_edit','call_id':call,'input':copy.deepcopy(args)},
                {'type':'tool_result','tool':'surgical_test_edit','call_id':call,'output_truncated':False,'output':output}])
            receipts.append({'call_id':call,'proposal_sha256':recovery.digest(args),
                'output_sha256':hashlib.sha256(output.encode()).hexdigest(),'category':[category],
                'driver_line':['137'] if call=='first' else [],'syntax_category':['unexpected_token'] if call=='first' else [],
                'ranges':[[512,512],[515,515],[528,528],[531,536]]})
        state['c10_diagnosis']['c09_evidence']['full_suite_failure']=state['functional_fragment_recovery']['history'][0]['failure']
        state['c10_syntax_recovery']['author_outcome']={'task_id':self.task['id'],'snapshot':state['snapshot'],
            'validation':state['validation'],'accepted_edits':0,'files_changed_from_seed':False,
            'suite_reexecuted':False,'syntax_feedback_visible':True,'identical_replay_blocked':True,'tool_receipts':receipts}
        state['current_execution_result']={'category':'syntax_rejection_then_replay_block','retry_authorized':False}
        return state,messages

    def test_decomposition_keeps_consumed_scope_and_gives_no_author_authority(self):
        state,messages=self.decomposition_fixture();original=copy.deepcopy(state)
        revised=recovery.prepare_decomposition(self.config,state,self.task,messages,93)
        self.assertEqual(state,original)
        self.assertFalse(revised['c10_decomposition']['author_scope_authorized'])
        self.assertEqual(revised['c10_decomposition']['prior']['functional_fragment_recovery'],state['functional_fragment_recovery'])
        self.assertNotIn('functional_diagnosis_receipt',revised)
        note=revised['functional_diagnosis']['note']
        self.assertLess(len(note)+512,4000)
        for required in ('QUERY:','STATUS:','512/515/528/531','partial checkpoint','no new suite ran','No author is authorized'):
            self.assertIn(required,note)
        for path in recovery.delivery.paths():self.assertIn(path,note)
        self.assertEqual(revised['functional_diagnosis']['failure_origin'],'historical_c09_progress_not_latest_execution')
        with self.assertRaises(ValueError):recovery.prepare_decomposition(self.config,revised,self.task,messages,93)

    def test_decomposition_denies_incomplete_rejections_or_missing_reserve(self):
        state,messages=self.decomposition_fixture()
        for mutation in ('truncated','different','changed','budget'):
            s=copy.deepcopy(state);m=copy.deepcopy(messages);remaining=93
            if mutation=='truncated':m[1]['output_truncated']=True
            elif mutation=='different':m[2]['input']['edits'][0]['new']='different'
            elif mutation=='changed':s['validation']=dict(s['validation'],test_sha256='f'*64)
            elif mutation=='budget':remaining=55
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):
                recovery.prepare_decomposition(self.config,s,self.task,m,remaining)

    def test_wrong_product_path_plan_gets_one_readonly_feedback_without_authority(self):
        state,messages=self.decomposition_fixture()
        revised=recovery.prepare_decomposition(self.config,state,self.task,messages,93)
        revised.update(stage='blocked',category='maintenance_diagnosis_driver_observation')
        revised['functional_diagnosis_receipt']={'classification':'DRIVER_OBSERVATION',
            'certificate':{'snapshot':revised['snapshot']['volume'],'test_sha256':revised['validation']['test_sha256']},
            'decision':{'reason':'DRIVER_OBSERVATION: QUERY wrap app.js lines 512/515/528/531.'}}
        prior=copy.deepcopy(revised)
        corrected=recovery.prepare_decomposition_feedback(revised)
        self.assertEqual(revised,prior)
        self.assertEqual(corrected['c10_decomposition']['plan_feedback']['prior_receipt'],prior['functional_diagnosis_receipt'])
        self.assertFalse(corrected['c10_decomposition']['author_scope_authorized'])
        self.assertIn('status_genA_urls',corrected['functional_diagnosis']['note'])
        self.assertIn('NOT app.js',corrected['functional_diagnosis']['note'])
        with self.assertRaises(ValueError):recovery.prepare_decomposition_feedback(corrected)

    def test_missing_classification_requires_fresh_decision_not_local_relabeling(self):
        state,messages=self.decomposition_fixture()
        state=recovery.prepare_decomposition(self.config,state,self.task,messages,93)
        state.update(stage='blocked',category='invalid_or_unread_driver_diagnosis')
        state['c10_decomposition']['plan_feedback']={'prior_receipt':{'invalid_path':True}}
        decision={'action':'request_test_revision','optional_files':[],
            'reason':'QUERY tests/test_incremental_u3.py envelopes; STATUS separately. Run259; QUERY is PARTIAL.'}
        task={'id':'cto'};cert={'task_id':'cto','snapshot':state['snapshot']['volume'],'test_sha256':state['validation']['test_sha256']}
        original=copy.deepcopy(decision)
        revised=recovery.prepare_classification_feedback(state,task,decision,cert)
        self.assertEqual(decision,original)
        self.assertEqual(revised['c10_decomposition']['classification_feedback']['actual_decision'],original)
        self.assertFalse(revised['c10_decomposition']['author_scope_authorized'])
        self.assertNotIn('functional_diagnosis_receipt',revised)
        self.assertIn('EXACTLY',revised['functional_diagnosis']['note'])
        with self.assertRaises(ValueError):recovery.prepare_classification_feedback(revised,task,decision,cert)
        wrong=dict(cert,test_sha256='f'*64)
        with self.assertRaises(ValueError):recovery.prepare_classification_feedback(state,task,decision,wrong)
