import copy
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
from broker import maintenance_delivery as delivery


class MaintenanceDeliveryTests(unittest.TestCase):
    def test_c10_contract_covers_query_status_and_nonrepeating_syntax_feedback(self):
        state={'functional_fragment_recovery':{'current':2,'scope':'response_envelope_c10_reviewed','diagnostics':{}},
            'functional_diagnosis_receipt':{'decision':{'reason':'independent current CTO diagnosis'}},
            'staged':{'driver_guard':{'line_ranges':True}}}
        note=delivery.functional_correction_note(state)
        for required in ('query response envelopes','512/515/528/531','status-only',
                'filter-open/filter-completed','pending_left','outer promise closure',
                'driver_line','syntax_category','identical_rejected_proposal'):
            self.assertIn(required,note)
        self.assertEqual(state['functional_fragment_recovery']['current'],2)
        self.assertNotIn('author_scope_authorized',state)

    def test_c10_requires_actual_c09_progress_and_new_independent_authority(self):
        import hashlib
        output='AssertionError: current gamma must paint'
        failure={'source_task':'author','volume':'snapshot','tests_executed':259,
            'exception_types':['AssertionError'],'missing_metadata_keys':[],'category':'executed_test_failure',
            'output_sha256':hashlib.sha256(output.encode()).hexdigest(),
            'failures':[{'test':'test_c10_stale_query_and_status_responses_are_discarded','kind':'FAIL'}]}
        validation={'test_sha256':'a'*64};snapshot={'volume':'snapshot'}
        evidence={'task_id':'author','snapshot':snapshot,'validation':validation,'full_suite_failure':failure,
            'c09_status':'passed_in_actual_full_suite'}
        state={'stage':'blocked','category':'maintenance_full_suite_failed','author_task':'author',
            'snapshot':snapshot,'validation':validation,'suite_failure':failure,'c09_checkpoint_receipt':evidence,
            'functional_diagnosis':{},'functional_diagnosis_receipt':{},'functional_correction':{},'functional_fragment_recovery':{}}
        revised=delivery.prepare_c10_diagnosis(copy.deepcopy(state),output)
        self.assertNotIn('functional_correction',revised)
        self.assertFalse(revised['c10_diagnosis']['author_scope_authorized'])
        self.assertIn('ONLY C10 failed',revised['functional_diagnosis']['note'])
        with self.assertRaises(ValueError):delivery.prepare_c10_diagnosis(revised,output)
        with self.assertRaises(ValueError):delivery.prepare_c10_diagnosis(copy.deepcopy(state),output+'tampered')
        bad=copy.deepcopy(state);bad['c09_checkpoint_receipt']['c09_status']='textual_claim'
        with self.assertRaises(ValueError):delivery.prepare_c10_diagnosis(bad,output)
        seed={'task_id':'author','snapshot':snapshot,'validation':validation}
        report={'classification':'DRIVER_OBSERVATION','certificate':{'task_id':'cto','snapshot':'snapshot','test_sha256':'a'*64},
            'decision':{'reason':'DRIVER_OBSERVATION: C10 needs actual generation responses.'}}
        revised['functional_diagnosis_receipt']=report
        revised['functional_correction']={'seed':seed,'certificate':report['certificate']}
        with self.assertRaises(ValueError):delivery.authorize_c10_correction(revised,seed,'stale-cto')
        with self.assertRaises(ValueError):delivery.authorize_c10_correction(revised,seed,'cto')
        revised['c10_diagnosis']['plan_verification']={'verified':True,'certificate':report['certificate'],
            'snapshot':snapshot,'validation':validation}
        delivery.authorize_c10_correction(revised,seed,'cto')
        self.assertEqual(delivery.fragment_seed(revised),seed)
        self.assertEqual(revised['functional_fragment_recovery']['current'],2)
        self.assertIn('C10 ONLY',delivery.functional_correction_note(revised))
        with self.assertRaises(ValueError):delivery.authorize_c10_correction(revised,seed,'cto')

    def test_live_items_experiment_is_bound_and_cannot_grant_c10(self):
        first={'variant':'baseline','tests':4,'errors':0,'driver_sha256':'a'*64,'output_sha256':'b'*64,
            'failures':['test_c09_query_survives_polling_and_create_and_complete','test_c10_stale_query_and_status_responses_are_discarded']}
        second=dict(first,variant='settle_create_from_live_items',driver_sha256='c'*64,
            failures=['test_c10_stale_query_and_status_responses_are_discarded'])
        proof={'operation':'in_memory_create_refresh_live_items_v1','manifest_sha256':'d'*64,
            'test_sha256':'e'*64,'source_modified':False,'assertions_modified':False,'fabricated_rows':False,
            'delivery_approval':False,'status':'experiment_only_not_green_or_approval','results':[first,second]}
        seed={'task_id':'author','snapshot':{'volume':'snapshot'},'validation':{'manifest_sha256':'d'*64,'test_sha256':'e'*64}}
        report={'classification':'DRIVER_OBSERVATION','certificate':{'task_id':'cto','snapshot':'snapshot','test_sha256':'e'*64},
            'decision':{'reason':'DRIVER_OBSERVATION: resolveNewest() before the create observation.'}}
        state={'validation':seed['validation'],'functional_diagnosis_receipt':report,
            'c09_progress_review':{'create_refresh_experiment':proof,'experiment_reassessment':{'experiment':proof,'author_scope_authorized':False}},
            'functional_correction':{'seed':seed,'certificate':report['certificate']},'staged':{'driver_guard':{'line_ranges':True}}}
        self.assertEqual(delivery.qualified_create_experiment(state),proof)
        for key in ('source_modified','assertions_modified','fabricated_rows','delivery_approval'):
            bad=copy.deepcopy(state);bad['c09_progress_review']['create_refresh_experiment'][key]=True
            with self.assertRaises(ValueError):delivery.qualified_create_experiment(bad)
        bad=copy.deepcopy(state);bad['validation']['test_sha256']='f'*64
        with self.assertRaises(ValueError):delivery.qualified_create_experiment(bad)
        delivery.authorize_experimental_c09(state,seed,'cto')
        self.assertEqual(delivery.fragment_seed(state),seed)
        self.assertFalse(state['c09_progress_review']['experiment_reassessment']['c10_scope_authorized'])
        self.assertIn('do not supply fabricated rows',delivery.functional_correction_note(state))
        report['decision']['reason']='DRIVER_OBSERVATION: resolveNewest() '+('x'*1150)
        self.assertLess(len(delivery.functional_correction_note(state)),3750)
        with self.assertRaises(ValueError):delivery.authorize_experimental_c09(state,seed,'cto')
        state['functional_fragment_recovery'].update(current=2,history=[{'seed':seed,'failure':{}}])
        with self.assertRaises(ValueError):delivery.fragment_seed(state)
        with self.assertRaises(ValueError):delivery.functional_correction_note(state)

    def test_changed_c09_failure_escalates_without_replaying_consumed_author_scope(self):
        import hashlib
        output="AssertionError: 'alpha new' not found in ['alpha one']\nAssertionError: current generation must paint"
        failure={'source_task':'new-author','volume':'new-snapshot','tests_executed':259,
            'exception_types':['AssertionError'],'output_sha256':hashlib.sha256(output.encode()).hexdigest(),
            'failures':[{'test':'test_c09_query_survives_polling_and_create_and_complete'},
                {'test':'test_c10_stale_query_and_status_responses_are_discarded'}]}
        state={'stage':'blocked','category':'maintenance_full_suite_failed','author_task':'new-author',
            'snapshot':{'volume':'new-snapshot'},'validation':{'test_sha256':'b'*64,'source_changed':True},
            'suite_failure':failure,'semantic_reassessment':{'authorized_phase':'C09',
                'author_scope_authorized':True,'c10_scope_authorized':False},
            'functional_diagnosis':{'old':True},'functional_diagnosis_receipt':{'old':True},
            'functional_correction':{'seed':{'task_id':'old-author','validation':{'test_sha256':'a'*64}}},
            'functional_fragment_recovery':{'scope':'response_envelope_semantic_c09','current':1}}
        revised=delivery.prepare_c09_progress_review(copy.deepcopy(state),output)
        self.assertNotIn('functional_correction',revised)
        self.assertNotIn('functional_fragment_recovery',revised)
        self.assertFalse(revised['c09_progress_review']['author_scope_authorized'])
        self.assertEqual(revised['c09_progress_review']['prior']['functional_correction'],state['functional_correction'])
        self.assertEqual(revised['functional_diagnosis']['author_task'],'new-author')
        self.assertIn('Do not repeat',revised['functional_diagnosis']['note'])
        self.assertLess(len(revised['functional_diagnosis']['note']),3900)
        with self.assertRaises(ValueError):delivery.prepare_c09_progress_review(revised,output)
        with self.assertRaises(ValueError):delivery.prepare_c09_progress_review(copy.deepcopy(state),output+'tampered')
        bad=copy.deepcopy(state);bad['validation']['test_sha256']='a'*64
        with self.assertRaises(ValueError):delivery.prepare_c09_progress_review(bad,output)

    def test_semantic_c09_authority_is_exact_and_cannot_start_c10(self):
        seed={'task_id':'author','snapshot':{'volume':'current'},'validation':{'test_sha256':'a'*64}}
        report={'classification':'DRIVER_OBSERVATION','certificate':{
            'task_id':'cto','snapshot':'current','test_sha256':'a'*64},
            'decision':{'reason':'DRIVER_OBSERVATION: app reads data.items; wrap arrays at455/463/495.'}}
        audit={'source_snapshot':'current','source_test_sha256':'a'*64,
            'c09_plan_scope_consistent':True,'c09_response_lines':[455,463,495],
            'source_modified':False,'tests_executed':False}
        state={'functional_diagnosis_receipt':report,'semantic_reassessment':{
            'author_scope_authorized':False,'review_outcome':{'receipt':report,'phase_scope_audit':audit}},
            'staged':{'driver_guard':{'line_ranges':True}},
            'functional_correction':{'seed':seed,'certificate':report['certificate']}}
        revised=copy.deepcopy(state)
        delivery.authorize_semantic_c09(revised,seed,'cto')
        self.assertTrue(revised['semantic_reassessment']['author_scope_authorized'])
        self.assertFalse(revised['semantic_reassessment']['c10_scope_authorized'])
        self.assertEqual(delivery.fragment_seed(revised),seed)
        note=delivery.functional_correction_note(revised)
        self.assertIn('wrap their existing arrays',note)
        self.assertIn('start_line,end_line,new',note)
        self.assertIn('will NOT automatically start',note)
        self.assertNotIn('remove the prior extra polling',note)
        with self.assertRaises(ValueError):delivery.authorize_semantic_c09(revised,seed,'cto')
        revised['functional_fragment_recovery'].update(current=2,history=[{'seed':seed,'failure':{}}])
        with self.assertRaises(ValueError):delivery.fragment_seed(revised)
        with self.assertRaises(ValueError):delivery.functional_correction_note(revised)
        for key in ('source_snapshot','source_test_sha256','c09_plan_scope_consistent','c09_response_lines','source_modified','tests_executed'):
            bad=copy.deepcopy(state);bad['semantic_reassessment']['review_outcome']['phase_scope_audit'][key]=None
            with self.assertRaises(ValueError):delivery.authorize_semantic_c09(bad,seed,'cto')
        with self.assertRaises(ValueError):delivery.authorize_semantic_c09(copy.deepcopy(state),seed,'stale-cto')

    def test_semantic_review_archives_old_author_authority_and_never_auto_retries(self):
        import hashlib
        output='259 tests ran, C09 and C10 failed'
        failure={'source_task':'author','volume':'current','tests_executed':259,'exception_types':['AssertionError'],
            'output_sha256':hashlib.sha256(output.encode()).hexdigest(),'failures':[
                {'test':'test_c09_query_survives_polling_and_create_and_complete'},
                {'test':'test_c10_stale_query_and_status_responses_are_discarded'}]}
        snapshot={'volume':'current'};validation={'test_sha256':'a'*64}
        state={'stage':'blocked','category':'maintenance_full_suite_failed','author_task':'author',
            'snapshot':snapshot,'validation':validation,'suite_failure':failure,
            'line_protocol_recovery':{'outcome':{'task_id':'author','snapshot':snapshot,'validation':validation,
                'suite_failure':failure,'selector_diagnostic':{'changes':[{'exact_selector_swap':True}]*3}}},
            'functional_diagnosis':{'old':True},'functional_diagnosis_receipt':{'old':True},
            'functional_correction':{'attempt_limit':1},'functional_fragment_recovery':{'current':1},
            'envelope_reassessment':{'author_scope_authorized':True}}
        revised=delivery.prepare_semantic_reassessment(copy.deepcopy(state),output)
        self.assertNotIn('envelope_reassessment',revised)
        self.assertNotIn('functional_correction',revised)
        self.assertEqual(revised['semantic_reassessment']['prior']['envelope_reassessment'],state['envelope_reassessment'])
        self.assertFalse(revised['semantic_reassessment']['author_scope_authorized'])
        self.assertIn('exact FILE line ranges',revised['functional_diagnosis']['note'])
        self.assertIn('DELIVERY_CURRENT_HARNESS_DIAGNOSIS_V1',revised['functional_diagnosis']['note'])
        self.assertLess(len(revised['functional_diagnosis']['note']),3900)
        with self.assertRaises(ValueError):delivery.prepare_semantic_reassessment(revised,output)
        with self.assertRaises(ValueError):delivery.prepare_semantic_reassessment(copy.deepcopy(state),output+'tampered')
        bad=copy.deepcopy(state);bad['line_protocol_recovery']['outcome']['selector_diagnostic']['changes'][0]['exact_selector_swap']=False
        with self.assertRaises(ValueError):delivery.prepare_semantic_reassessment(bad,output)
    def test_v4_recovery_requires_new_qualified_protocol_and_preserves_consumed_scope(self):
        task={'id':'failed','status':'completed','issue_id':'issue','wakeup_id':'wake'}
        proof={'status':'passed','protocol':'typed_driver_lines_v4','worker_image':'new','delivery_approval':False,'network':'none','uid':10000}
        for key in ('actual_registry','actual_default_selection','actual_acp_selection','line_range_registry_qualified',
                'line_range_proxy_schema_qualified','line_range_atomic_rejection','line_range_duplicate_selection','line_range_stale_denied','credentials_absent'):proof[key]=True
        outcome={'task_id':'failed','files_modified':False,'delivery_approval':False,'functional_suite_executed':False,
            'tool_failures':[{'category':'missing_exact_fragment'},{'category':'unchanged_pair'}]}
        state={'stage':'blocked','category':'unchanged_functional_driver','author_task':'failed','issue_id':'issue','wakeup_id':'wake',
            'snapshot':{'volume':'original'},'validation':{'test_sha256':'a'*64},'fragment_feedback_recovery':{'outcome':outcome},
            'staged':{'driver_guard':{'worker_image':'new','qualification':proof,'line_ranges':True}},
            'line_protocol_worker_revision':{'qualification':proof,'prior_guard':{'worker_image':'old'},'canonical_handoff_probe':{'passed':True}},
            'functional_fragment_recovery':{'current':1,'instruction_revision':3,'scope':'response_envelope_compacted','attempt_limit_per_fragment':1}}
        with patch.object(delivery,'fragment_seed',return_value={'validation':{'test_sha256':'a'*64}}):
            revised,_=delivery.prepare_line_protocol_recovery(copy.deepcopy(state),task,52)
            self.assertEqual(revised['line_protocol_recovery']['prior_scope'],state['functional_fragment_recovery'])
            self.assertEqual(revised['fragment_feedback_recovery'],state['fragment_feedback_recovery'])
            self.assertEqual(revised['functional_fragment_recovery']['instruction_revision'],4)
            self.assertFalse(revised['line_protocol_recovery']['delivery_approval'])
            with self.assertRaises(ValueError):delivery.prepare_line_protocol_recovery(revised,task,52)
            with self.assertRaises(ValueError):delivery.prepare_line_protocol_recovery(copy.deepcopy(state),dict(task,wakeup_id='old'),52)
            with self.assertRaises(ValueError):delivery.prepare_line_protocol_recovery(copy.deepcopy(state),task,47)
            for change in ('seed','probe','qualification','protocol'):
                bad=copy.deepcopy(state)
                if change=='seed':bad['validation']['test_sha256']='b'*64
                elif change=='probe':bad['line_protocol_worker_revision']['canonical_handoff_probe']['passed']=False
                elif change=='qualification':bad['staged']['driver_guard']['qualification']['line_range_registry_qualified']=False
                else:bad['staged']['driver_guard']['line_ranges']=False
                with self.assertRaises(ValueError):delivery.prepare_line_protocol_recovery(bad,task,52)
    def test_feedback_recovery_is_bound_to_new_worker_unchanged_seed_and_one_attempt(self):
        task={'id':'failed','status':'completed','issue_id':'issue','wakeup_id':'wake'}
        proof={'status':'passed','schema':'surgical-driver-registry-probe-v3','worker_image':'new',
            'delivery_approval':False,'network':'none','uid':10000,**{k:True for k in (
                'actual_registry','actual_acp_selection','fragment_identity_feedback_preserves_bytes','fragment_identity_feedback_acp_visible')}}
        state={'stage':'blocked','category':'unchanged_functional_driver','author_task':'failed','issue_id':'issue','wakeup_id':'wake',
            'snapshot':{'volume':'unchanged'},'validation':{'test_sha256':'a'*64},
            'staged':{'driver_guard':{'worker_image':'new','qualification':proof}},
            'fragment_feedback_worker_revision':{'qualification':proof,'prior_guard':{'worker_image':'old'}},
            'functional_fragment_recovery':{'current':1,'instruction_revision':2,'scope':'response_envelope_compacted'},
            'current_context_recovery':{'outcome':{'task_id':'failed','files_modified':False,'category':'unchanged_functional_driver',
                'fragment_diagnostic':{'source_sha256':'a'*64,'proposals':[{'fragments':[{'matches':2}]},{'fragments':[{'matches':2}]}]}}}}
        with patch.object(delivery,'fragment_seed',return_value={'validation':{'test_sha256':'a'*64}}):
            revised,_=delivery.prepare_fragment_feedback_recovery(copy.deepcopy(state),task,54)
            self.assertEqual(revised['fragment_feedback_recovery']['prior_scope'],state['functional_fragment_recovery'])
            self.assertEqual(revised['current_context_recovery'],state['current_context_recovery'])
            self.assertEqual(revised['functional_fragment_recovery']['instruction_revision'],3)
            self.assertIn('fragment_index/match_count/hint',delivery.functional_correction_note(dict(revised,
                functional_fragment_recovery=dict(revised['functional_fragment_recovery'],diagnostics=[]),
                functional_diagnosis_receipt={'decision':{'reason':'authority'}})))
            with self.assertRaises(ValueError):delivery.prepare_fragment_feedback_recovery(revised,task,54)
            with self.assertRaises(ValueError):delivery.prepare_fragment_feedback_recovery(copy.deepcopy(state),dict(task,wakeup_id='old'),54)
            with self.assertRaises(ValueError):delivery.prepare_fragment_feedback_recovery(copy.deepcopy(state),task,47)
            for change in ('seed','worker','proof'):
                bad=copy.deepcopy(state)
                if change=='seed':bad['validation']['test_sha256']='b'*64
                elif change=='worker':bad['fragment_feedback_worker_revision']['prior_guard']['worker_image']='new'
                else:bad['staged']['driver_guard']['qualification']['fragment_identity_feedback_acp_visible']=False
                with self.assertRaises(ValueError):delivery.prepare_fragment_feedback_recovery(bad,task,54)
    def test_current_runtime_recovery_preserves_failed_attempt_and_is_one_shot(self):
        import hashlib
        digest=lambda text:hashlib.sha256(text.encode()).hexdigest()
        output='actual 259-test failed suite'
        task={'id':'task','issue_id':'issue','wakeup_id':'wake','status':'completed','handoff_note':'C09 RESPONSE ENVELOPE ONLY'}
        issue={'id':'issue','description':'Historical syntax/C10 instruction'}
        images={'controller_image':'sha256:'+'a'*64,'proxy_image':'sha256:'+'b'*64}
        state={'stage':'blocked','category':'maintenance_full_suite_failed','author_task':'task','issue_id':'issue','wakeup_id':'wake',
            'snapshot':{'volume':'failed'},'validation':{'test_sha256':'c'*64},'phase1_note_revision':{'failed_task':'prior'},
            'functional_fragment_recovery':{'scope':'response_envelope_compacted','current':1,'instruction_revision':1,'attempt_limit_per_fragment':1},
            'suite_failure':{'source_task':'task','tests_executed':259,'output_sha256':digest(output)}}
        state['current_phase_context_repair']={**images,'classification':'historical_issue_and_proxy_instructions_conflicted_with_current_phase',
            'failed_task':'task','delivery_approval':False,'prior_snapshot':state['snapshot'],'prior_validation':state['validation'],
            'prior_failure':state['suite_failure'],'historical_description_sha256':digest(issue['description']),
            'handoff_sha256':digest(task['handoff_note']),'offline_tests':{'executed':1219,'failures':0,'errors':0},
            'isolated_real_state_probe':{k:True for k in ('passed','blocked_task_denied','current_C09_scope_injected','historical_description_excluded')}}
        with patch.object(delivery,'fragment_seed',return_value={'task_id':'compacted'}) as seed:
            revised,receipt=delivery.prepare_current_context_recovery(copy.deepcopy(state),task,issue,output,images,56)
            self.assertEqual(receipt,{'task_id':'compacted'})
            self.assertEqual(revised['current_context_recovery']['prior_scope'],state['functional_fragment_recovery'])
            self.assertEqual(revised['current_context_recovery']['prior_failure'],state['suite_failure'])
            self.assertEqual(revised['phase1_note_revision'],state['phase1_note_revision'])
            self.assertEqual(revised['functional_fragment_recovery']['instruction_revision'],2)
            self.assertFalse(revised['current_context_recovery']['delivery_approval'])
            with self.assertRaises(ValueError):delivery.prepare_current_context_recovery(revised,task,issue,output,images,56)
            for changed_task,changed_issue,changed_output,changed_images,budget in (
                (dict(task,wakeup_id='stale'),issue,output,images,56),
                (task,dict(issue,description='changed'),output,images,56),
                (task,issue,output+'tampered',images,56),
                (task,issue,output,dict(images,controller_image='old'),56),
                (task,issue,output,images,47)):
                with self.assertRaises(ValueError):delivery.prepare_current_context_recovery(copy.deepcopy(state),changed_task,changed_issue,changed_output,changed_images,budget)
            seed.assert_called_once()
    def test_envelope_reassessment_preserves_attempts_and_requires_current_durable_failure(self):
        import hashlib
        output='259 tests C09 and C10 failed'
        failure={'source_task':'current','volume':'current-volume','tests_executed':259,
            'exception_types':['AssertionError'],'output_sha256':hashlib.sha256(output.encode()).hexdigest(),
            'failures':[{'test':'test_c09_query_survives_polling_and_create_and_complete'},
                {'test':'test_c10_stale_query_and_status_responses_are_discarded'}]}
        validation={'test_sha256':'a'*64}
        snapshot={'volume':'current-volume'}
        analysis={'classification':'driver_response_envelope_mismatch','performed_by':'operator_readonly_diagnostic',
            'snapshot':snapshot,'author_task':'current','test_sha256':'a'*64,
            'full_suite_output_sha256':failure['output_sha256'],'observations':{'rendered_after_poll':[]}}
        state={'stage':'blocked','category':'maintenance_full_suite_failed','author_task':'current',
            'snapshot':snapshot,'validation':validation,'suite_failure':failure,
            'functional_fragment_failure_analysis':analysis,'functional_diagnosis':{'old':True},
            'functional_diagnosis_receipt':{'old':True},'functional_correction':{'attempt_limit':1},
            'functional_fragment_recovery':{'current':1,'attempt_limit_per_fragment':1}}
        revised=delivery.prepare_envelope_reassessment(copy.deepcopy(state),output)
        self.assertEqual(revised['envelope_reassessment']['prior']['functional_correction'],state['functional_correction'])
        self.assertNotIn('functional_correction',revised)
        self.assertEqual(revised['functional_diagnosis']['snapshot'],snapshot)
        self.assertIn('data.items',revised['functional_diagnosis']['note'])
        self.assertIn('DELIVERY_TECHNICAL_LENGTH_FEEDBACK_V1',revised['functional_diagnosis']['note'])
        self.assertFalse(revised['delivery_approval'])
        with self.assertRaises(ValueError):delivery.prepare_envelope_reassessment(revised,output)
        for key,value in [('snapshot',{'volume':'old'}),('full_suite_output_sha256','f'*64),('test_sha256','b'*64)]:
            mutated=copy.deepcopy(state);mutated['functional_fragment_failure_analysis'][key]=value
            with self.assertRaises(ValueError):delivery.prepare_envelope_reassessment(mutated,output)
        with self.assertRaises(ValueError):delivery.prepare_envelope_reassessment(copy.deepcopy(state),output+'altered')
    def test_fragment_chain_requires_actual_full_suite_progress(self):
        seed={'task_id':'old','checkpoint':2,'snapshot':{'volume':'original'},'validation':{'test_sha256':'a'*64}}
        state={'functional_correction':{'seed':seed,'certificate':{'task_id':'cto'}},
            'functional_diagnosis_receipt':{'certificate':{'task_id':'cto'},'classification':'DRIVER_OBSERVATION'},
            'functional_fragment_recovery':{'current':1,'history':[],'original_seed':seed,'diagnostics':[],
                'attempt_limit_per_fragment':1}}
        self.assertEqual(delivery.fragment_seed(state),seed)
        self.assertIn('C09 ONLY',delivery.functional_correction_note(state))
        next_seed=dict(seed,task_id='part1',snapshot={'volume':'new'},validation={'test_sha256':'b'*64})
        failure={'category':'executed_test_failure','tests_executed':259,'source_task':'part1','volume':'new',
            'exception_types':['AssertionError'],'missing_metadata_keys':[],
            'failures':[{'kind':'FAIL','test':'test_c10_stale_query_and_status_responses_are_discarded'}]}
        recovery=state['functional_fragment_recovery'];recovery.update(current=2,history=[{'seed':next_seed,'failure':failure}])
        self.assertEqual(delivery.fragment_seed(state),next_seed)
        self.assertIn('C10 ONLY',delivery.functional_correction_note(state))
        for key,value in [('tests_executed',258),('source_task','wrong'),('volume','old'),('failures',[]),('exception_types',['KeyError']),('missing_metadata_keys',['report'])]:
            changed=copy.deepcopy(state);changed['functional_fragment_recovery']['history'][0]['failure'][key]=value
            with self.assertRaises(ValueError):delivery.fragment_seed(changed)
    def test_compacted_seed_requires_ast_identity_and_real_suite_before_author_grant(self):
        original={'task_id':'old','checkpoint':2,'snapshot':{'volume':'old'},
            'validation':{'test_sha256':'a'*64,'manifest_sha256':'b'*64}}
        compacted={'task_id':'failed','checkpoint':2,'snapshot':{'volume':'compacted'},
            'validation':{'test_sha256':'c'*64,'manifest_sha256':'d'*64}}
        state={'functional_correction':{'seed':original,'certificate':{'task_id':'cto'}},
            'functional_diagnosis_receipt':{'certificate':{'task_id':'cto'},'classification':'DRIVER_OBSERVATION'},
            'functional_fragment_recovery':{'scope':'response_envelope_compacted','current':1,'history':[],
                'original_seed':original,'attempt_limit_per_fragment':1},
            'comment_compaction':{'status':'passed','seed':compacted,'source_seed':original,
                'baseline_failure_verified':{'tests_executed':259,'source_task':'failed','volume':'compacted'},
                'receipt':{'operation':'controller_driver_comment_compaction','javascript_ast_preserved':True,
                    'non_driver_ast_preserved':True,'delivery_approval':False,'source_sha256':'a'*64,
                    'compacted_sha256':'c'*64,'manifest_sha256':'d'*64}}}
        self.assertEqual(delivery.fragment_seed(state),compacted)
        state['functional_diagnosis_receipt']['decision']={'reason':'DRIVER_OBSERVATION: wrap items; Implement future status segment.'}
        state['functional_fragment_recovery']['diagnostics']={}
        note=delivery.functional_correction_note(state)
        self.assertIn('C09 RESPONSE ENVELOPE ONLY',note)
        self.assertNotIn('Implement future status segment',note)
        for key,value in [('javascript_ast_preserved',False),('source_sha256','f'*64),('compacted_sha256','e'*64)]:
            altered=copy.deepcopy(state);altered['comment_compaction']['receipt'][key]=value
            with self.assertRaises(ValueError):delivery.fragment_seed(altered)
        altered=copy.deepcopy(state);altered['comment_compaction']['baseline_failure_verified']['tests_executed']=258
        with self.assertRaises(ValueError):delivery.fragment_seed(altered)
    def test_functional_diagnosis_requires_real_suite_and_cannot_approve_product(self):
        import hashlib
        output='immutable full suite output'
        digest=hashlib.sha256(output.encode()).hexdigest()
        failure={'category':'executed_test_failure','source_task':'task','volume':'frozen',
            'tests_executed':259,'output_sha256':digest,'failures':[
                {'test':'test_c09_query_survives_polling_and_create_and_complete'},
                {'test':'test_c10_stale_query_and_status_responses_are_discarded'}]}
        state={'stage':'blocked','category':'maintenance_full_suite_failed','author_task':'task',
            'snapshot':{'volume':'frozen'},'validation':{'manifest_sha256':'a'*64,'test_sha256':'b'*64},'suite_failure':failure}
        row={'task_id':'task','status':'failed','manifest_sha256':'a'*64,'receipt':json.dumps({'failure':failure})}
        planned=delivery.prepare_functional_diagnosis(copy.deepcopy(state),row,output)
        self.assertEqual(planned['stage'],'maintenance_functional_diagnosis_dispatch')
        self.assertLess(len(planned['functional_diagnosis']['note']),3900)
        with self.assertRaises(ValueError):delivery.prepare_functional_diagnosis(planned,row,output)
        with self.assertRaises(ValueError):delivery.prepare_functional_diagnosis(copy.deepcopy(state),row,output+'changed')
        cert={'snapshot':'frozen','test_sha256':'b'*64}
        for classification,action in (('DRIVER_OBSERVATION','request_test_revision'),('PRODUCT_REGRESSION','escalate_cto'),('UNRESOLVED','escalate_cto')):
            decision={'action':action,'reason':classification+': exact source anchor and next evidence.','optional_files':[]}
            report=delivery.qualify_functional_decision(planned,decision,cert)
            self.assertEqual(report['classification'],classification);self.assertFalse(report['delivery_approval'])
        with self.assertRaises(ValueError):delivery.qualify_functional_decision(planned,{'action':'request_test_revision','reason':'PRODUCT_REGRESSION: bypass guard'},cert)
        with self.assertRaises(ValueError):delivery.qualify_functional_decision(planned,{'action':'request_test_revision','reason':'DRIVER_OBSERVATION: fix'},dict(cert,snapshot='stale'))
        planned['functional_diagnosis']['validation']['node_syntax_valid']=True
        note=delivery.revised_functional_note(planned)
        self.assertLess(len(note),3900);self.assertIn('Node check PASSED',note)
        self.assertIn('259 tests RAN',note);self.assertIn('out.complete_urls=getCalls()',note)
        self.assertIn('CORRECTION 1/1',note)
        for phrase in ('DRIVER_BODY is Node-syntax-invalid','harness never executes','node --check fails'):
            with self.assertRaises(ValueError):delivery.qualify_functional_decision(planned,{
                'action':'request_test_revision','reason':'DRIVER_OBSERVATION: '+phrase},cert)

    def setUp(self):
        self.con=sqlite3.connect(':memory:');self.con.row_factory=sqlite3.Row
        self.con.execute('CREATE TABLE harness_repair_tasks(source_task TEXT,config TEXT,state TEXT)')
        self.con.execute('CREATE TABLE test_revision_trials(issue_id TEXT,config TEXT)')
        self.con.execute('INSERT INTO test_revision_trials VALUES (?,?)',('child',json.dumps({'reviewer':'reviewer'})))
        self.config={'author':'author','cto':'cto'}
        self.state={'issue_id':'child','stage':'maintenance_suite_pending','author_task':'task',
            'snapshot':{'volume':'frozen'},'validation':{'manifest_sha256':'a'*64,'test_sha256':'b'*64}}
        self.con.execute('INSERT INTO harness_repair_tasks VALUES (?,?,?)',('source',json.dumps(self.config),json.dumps(self.state)))
        @contextmanager
        def db():
            with self.con:yield self.con
        self.result={'portable':True,'baseline_tests_intact':True,'manifest_sha256':'a'*64,'tests':3,
            'suite':{'tests':3,'test_image':'test-runner@sha256:'+'c'*64,'test_command':['python','-m','unittest','discover'],
                'output_sha256':'d'*64,'output':'Ran 3 tests\nOK'}}
        self.b=SimpleNamespace(db=db,LOCK=threading.RLock(),OWNER='owner',
            docker=Mock(return_value={'Labels':{'delivery-kit.owner':'owner','delivery-kit.source-task':'task'}}),
            validate_frozen_delivery=Mock(return_value=self.result))
        self.settings={'agents':{'reviewer':'planning'}}
        self.verify=patch.object(delivery.admission_controls_spike,'verify_current');self.verify.start()
        self.validator=patch.object(delivery,'validate_maintenance',self.b.validate_frozen_delivery);self.validator.start()
    def tearDown(self):self.validator.stop();self.verify.stop();self.con.close()
    def read_state(self):return json.loads(self.con.execute('SELECT state FROM harness_repair_tasks').fetchone()[0])
    def write_state(self,state):self.con.execute('UPDATE harness_repair_tasks SET state=?',(json.dumps(state),));self.con.commit()
    def run_step(self):return delivery.advance(self.b,'source',self.config,self.read_state(),self.settings)
    def test_controller_suite_uses_frozen_snapshot_and_durable_receipt(self):
        self.assertTrue(self.run_step())
        self.b.validate_frozen_delivery.assert_called_once()
        args=self.b.validate_frozen_delivery.call_args.args
        self.assertIs(args[0],self.b);self.assertEqual(args[1],self.config)
        self.assertEqual(args[2]['snapshot'],{'volume':'frozen'});self.assertEqual(args[2]['author_task'],'task')
        state=self.read_state();self.assertEqual(state['stage'],'maintenance_review_dispatch')
        self.assertFalse(state['suite_receipt']['functional_red']);self.assertFalse(state['suite_receipt']['delivery_approval'])
        receipt=json.loads(self.con.execute('SELECT receipt FROM maintenance_suite_runs').fetchone()[0])
        self.assertEqual(receipt['output'],self.result['suite']['output'])
    def test_old_snapshot_cannot_supply_suite_receipt(self):
        with self.assertRaises(ValueError):delivery.receipt(dict(self.result,manifest_sha256='e'*64),self.state)
        self.result['baseline_tests_intact']=False
        with self.assertRaises(ValueError):delivery.receipt(self.result,self.state)
    def test_scoped_suite_recovery_preserves_failed_run_and_is_idempotent(self):
        state=dict(self.state,stage='blocked',category='maintenance_full_suite_infrastructure_failed',staged={'current':2})
        state['validation']={**state['validation'],**{k:True for k in ('python_syntax_valid','node_syntax_valid','test_methods_preserved','non_driver_ast_preserved','source_changed')}}
        self.write_state(state)
        self.con.execute('CREATE TABLE leases(status TEXT)');delivery.initialize(self.con)
        failed=json.dumps({'error_type':'ValueError','failure':None})
        self.con.execute('INSERT INTO maintenance_suite_runs VALUES (?,?,?,?,?)',('task','source','a'*64,'failed',failed));self.con.commit()
        result=delivery.resume_scoped_suite(self.b,'source')
        self.assertEqual(result['stage'],'maintenance_suite_pending')
        recovery=self.read_state()['scoped_suite_recovery']
        self.assertEqual(recovery['previous_run']['receipt'],failed)
        self.assertFalse(recovery['delivery_approval'])
        self.assertTrue(delivery.resume_scoped_suite(self.b,'source')['reused'])
        self.assertEqual(self.con.execute('select count(*) from maintenance_suite_runs').fetchone()[0],0)
    def test_automatic_functional_registration_failure_does_not_repeat(self):
        from broker import harness_repair_task as repair
        self.write_state(dict(self.state,stage='blocked',category='maintenance_full_suite_failed'))
        with tempfile.TemporaryDirectory() as folder:
            self.b.STATE=Path(folder);(self.b.STATE/'native.json').write_text('{}')
            with patch.object(delivery,'register_functional_diagnosis',side_effect=ValueError('missing receipt')) as register:
                repair.tick(self.b);repair.tick(self.b)
                register.assert_called_once_with(self.b,'source')
        self.assertEqual(self.read_state()['category'],'functional_diagnosis_registration_failed')
    def test_envelope_auto_admission_waits_for_idle_and_failure_does_not_loop(self):
        from broker import harness_repair_task as repair
        state=dict(self.state,stage='blocked',category='maintenance_diagnosis_driver_observation',
            envelope_reassessment={'author_scope_authorized':True})
        self.write_state(state)
        self.con.execute('CREATE TABLE leases(status TEXT)');self.con.execute("INSERT INTO leases VALUES ('closing')");self.con.commit()
        with tempfile.TemporaryDirectory() as folder:
            self.b.STATE=Path(folder);(self.b.STATE/'native.json').write_text('{}')
            with patch.object(delivery,'arm_functional_correction',side_effect=ValueError('invalid certificate')) as admit:
                repair.tick(self.b);admit.assert_not_called()
                self.con.execute('DELETE FROM leases');self.con.commit()
                repair.tick(self.b);repair.tick(self.b)
                admit.assert_called_once_with(self.b,'source')
        self.assertEqual(self.read_state()['category'],'envelope_author_admission_failed')
    def test_phase1_instruction_revision_preserves_failed_delivery_and_does_not_replay(self):
        import hashlib
        seed={'task_id':'task','snapshot':{'volume':'frozen'},'checkpoint':2,'validation':{'test_sha256':'a'*64}}
        original={'task_id':'original','snapshot':{'volume':'original'},'checkpoint':2,'validation':{'test_sha256':'b'*64}}
        seed['validation']['manifest_sha256']='c'*64
        output='actual C09 failure';digest=hashlib.sha256(output.encode()).hexdigest()
        state=dict(self.state,stage='blocked',category='maintenance_full_suite_failed',wakeup_id='wake',
            suite_failure={'source_task':'task','output_sha256':digest},functional_correction={'seed':original,'certificate':{}},
            functional_diagnosis_receipt={'certificate':{},'classification':'DRIVER_OBSERVATION','decision':{'reason':'future status instruction'}},
            functional_fragment_recovery={'scope':'response_envelope_compacted','current':1,'history':[],
                'original_seed':original,'diagnostics':{},'attempt_limit_per_fragment':1},
            comment_compaction={'status':'passed','source_seed':original,'seed':seed,
                'baseline_failure_verified':{'tests_executed':259,'source_task':'task','volume':'frozen'},
                'receipt':{'operation':'controller_driver_comment_compaction','javascript_ast_preserved':True,
                    'non_driver_ast_preserved':True,'delivery_approval':False,'source_sha256':'b'*64,
                    'compacted_sha256':'a'*64,'manifest_sha256':'c'*64},
                'author_failure_analysis':{'task_id':'task','classification':'out_of_phase_change',
                'handoff_has_C09_scope':True,'handoff_also_quotes_future_CTO_status_instruction':True,'suite_output_sha256':digest}})
        self.write_state(state);self.con.execute('CREATE TABLE leases(status TEXT)')
        self.con.execute('CREATE TABLE frozen_suite_failures(task_id TEXT,output_sha256 TEXT,output TEXT)')
        self.con.execute('INSERT INTO frozen_suite_failures VALUES (?,?,?)',('task',digest,output));self.con.commit()
        task={'id':'task','status':'completed','wakeup_id':'wake','handoff_note':'C09 RESPONSE ENVELOPE ONLY\nCTO recommendation: future status instruction'}
        fx=Mock();fx.remaining_calls.return_value=60
        with tempfile.TemporaryDirectory() as folder:
            self.b.STATE=Path(folder);(self.b.STATE/'native.json').write_text('{}')
            with patch.object(delivery.handoff_runtime,'Effects',return_value=fx),patch.object(delivery.native,'task_record',return_value=task),patch.object(delivery.native,'issue_task_runs',return_value=[]):
                self.assertEqual(delivery.revise_compacted_phase1_note(self.b,'source')['stage'],'checkpoint_dispatch_intent')
                self.assertTrue(delivery.revise_compacted_phase1_note(self.b,'source')['reused'])
        revised=self.read_state()
        self.assertEqual(revised['phase1_note_revision']['prior_snapshot'],state['snapshot'])
        self.assertEqual(revised['phase1_note_revision']['prior_failure'],state['suite_failure'])
        self.assertEqual(revised['functional_fragment_recovery']['instruction_revision'],1)
    def test_functional_correction_is_one_shot_and_seeds_current_frozen_revision(self):
        from broker import harness_repair_task as h
        proof=json.loads((Path(__file__).resolve().parents[1]/'evaluation/SURGICAL-DRIVER-V3-QUALIFICATION-2026-10-04.json').read_text())
        facts=dict(self.state['validation'],source_changed=True,python_syntax_valid=True,node_syntax_valid=True,
            test_methods_preserved=True,non_driver_ast_preserved=True,bytes=32057)
        state=dict(self.state,stage='blocked',category='maintenance_diagnosis_driver_observation',validation=facts,
            diagnosis={'wakeup_id':'cto-wake'},wakeup_id='old-author-wake',
            staged={'current':2,'history':[{'checkpoint':1,'validation':dict(facts,test_sha256='e'*64)}],
                'driver_guard':{'qualification':proof,'worker_image':proof['worker_image']}})
        state['functional_diagnosis']={'snapshot':state['snapshot'],'validation':facts,'failure':{'output_sha256':'f'*64}}
        task={'id':'cto-task','issue_id':'child','agent_id':'cto','status':'completed','wakeup_id':'cto-wake'}
        decision={'action':'request_test_revision','reason':'DRIVER_OBSERVATION: drain held polling GET and capture actual status generation observations.','optional_files':[]}
        reads={p:{'lines':5,'total_lines':5} for p in h.diagnosis_paths()}
        cert=h.qualify_diagnosis(self.config,state,task,decision,reads)
        state['functional_diagnosis_receipt']=delivery.qualify_functional_decision(state,decision,cert)
        self.write_state(state)
        self.con.execute('CREATE TABLE leases(status TEXT)')
        self.con.execute('UPDATE test_revision_trials SET config=?',(json.dumps({'harness_maintenance_only':True}),));self.con.commit()
        fx=Mock();fx.decision.return_value=decision;fx.read_evidence.return_value=reads;fx.remaining_calls.return_value=70
        self.b.docker.side_effect=lambda verb,path: {'Id':proof['worker_image']} if path.startswith('/images/') else {'Labels':{'delivery-kit.owner':'owner','delivery-kit.source-task':'task'}}
        with tempfile.TemporaryDirectory() as folder:
            self.b.STATE=Path(folder);(self.b.STATE/'native.json').write_text('{}')
            with patch.object(delivery.handoff_runtime,'Effects',return_value=fx),patch.object(delivery.native,'task_record',return_value=task) as native_task,patch.object(delivery.native,'issue_task_runs',return_value=[]):
                self.assertEqual(delivery.arm_functional_correction(self.b,'source')['stage'],'checkpoint_dispatch_intent')
                self.assertTrue(delivery.arm_functional_correction(self.b,'source')['reused']);native_task.assert_called_once()
        result=self.read_state();seed=result['functional_correction']['seed']
        self.assertEqual(seed['validation']['test_sha256'],'b'*64)
        self.assertEqual(result['staged']['history'][0]['validation']['test_sha256'],'e'*64)
        self.assertEqual(json.loads(self.con.execute('SELECT config FROM test_revision_trials').fetchone()[0])['maintenance_seed']['receipt'],seed)
        self.assertIn('Fix C09',delivery.functional_correction_note(result))
        messages=[]
        for number,category in enumerate(('no_bounded_change','driver_syntax_invalid')):
            messages.extend([{'type':'tool_use','tool':'surgical_test_edit','call_id':str(number)},
                {'type':'tool_result','call_id':str(number),'output':'surgical_edit_rejected:'+category+':fixed_action'}])
        result.update(stage='blocked',category='unchanged_functional_driver',author_task='failed',wakeup_id='failed-wake',snapshot={'volume':'unchanged-new'})
        result['functional_correction_failure_receipt']={'rejected_operations':h.rejected_driver_operations(messages)}
        self.write_state(result)
        author={'id':'failed','status':'completed','wakeup_id':'failed-wake'}
        diagnostics=[{'category':category,'source_sha256':'b'*64,'files_modified':False,'delivery_approval':False}
            for category in ('no_bounded_change','driver_syntax_invalid')]
        with tempfile.TemporaryDirectory() as folder:
            self.b.STATE=Path(folder);(self.b.STATE/'native.json').write_text('{}')
            with patch.object(delivery.handoff_runtime,'Effects',return_value=fx),patch.object(delivery.native,'task_record',side_effect=lambda settings,identity,agent: task if agent=='cto' else author),patch.object(delivery.native,'task_messages',return_value=messages),patch.object(delivery.native,'issue_task_runs',return_value=[]),patch.object(delivery,'proposal_diagnostics',return_value=diagnostics):
                self.assertEqual(delivery.arm_functional_fragments(self.b,'source')['fragment'],1)
                self.assertTrue(delivery.arm_functional_fragments(self.b,'source')['reused'])
        recovered=self.read_state()
        self.assertEqual(recovered['functional_correction'],result['functional_correction'])
        self.assertEqual(recovered['functional_fragment_recovery']['failed_task'],'failed')
        self.assertEqual(recovered['staged']['history'],result['staged']['history'])
    def test_interrupted_suite_blocks_without_rerun(self):
        import time
        state=dict(self.state,stage='maintenance_suite_running',suite_started_at=time.time()-181)
        self.write_state(state);self.run_step()
        self.assertEqual(self.read_state()['category'],'interrupted_maintenance_full_suite')
        self.b.validate_frozen_delivery.assert_not_called()

    def test_c10_query_partial_is_durable_blocked_and_never_legacy_dispatch(self):
        from broker import c10_checkpoint_contract as phases,suite_failure
        state=copy.deepcopy(self.state)
        state['c10_checkpoints']={'schema':phases.SCHEMA,'phase':'QUERY',
            'seed':{'validation':{'test_sha256':'c'*64}},
            'scope_receipt':{'schema':phases.SCHEMA,'phase':'QUERY','scope_verified':True,
                'seed_test_sha256':'c'*64,'test_sha256':'b'*64,'manifest_sha256':'a'*64,'delivery_approval':False}}
        state['functional_fragment_recovery']={'current':1,'history':[]}
        self.write_state(state)
        output=('ERROR: '+phases.C10+' (tests.test_incremental_u3.DriverTests)\n'
            "KeyError: 'status_genA_urls'\nRan 259 tests in 1.0s\nFAILED (errors=1)\n")
        failure=suite_failure.evidence(1,output,'task','frozen')
        failure['diagnostic_read_files']=['app/static/app.js','app/static/index.html','tests/test_incremental_u3.py']
        self.con.execute('CREATE TABLE frozen_suite_failures(task_id TEXT,output_sha256 TEXT,output TEXT)')
        self.con.execute('INSERT INTO frozen_suite_failures VALUES (?,?,?)',('task',failure['output_sha256'],output));self.con.commit()
        self.b.validate_frozen_delivery.side_effect=suite_failure.FrozenSuiteFailure(failure)
        self.run_step();updated=self.read_state()
        self.assertEqual(updated['stage'],'blocked')
        self.assertEqual(updated['category'],'c10_query_partial_requires_status_admission')
        self.assertFalse(updated['c10_checkpoints']['query_receipt']['green'])
        self.assertEqual(updated['functional_fragment_recovery'],state['functional_fragment_recovery'])
        self.assertNotIn('maintenance_seed',json.loads(self.con.execute('SELECT config FROM test_revision_trials').fetchone()[0]))
        self.assertFalse(self.run_step());self.b.validate_frozen_delivery.assert_called_once()

    def test_c10_query_unexpected_green_or_missing_durable_output_never_approves(self):
        from broker import c10_checkpoint_contract as phases,suite_failure
        state=copy.deepcopy(self.state)
        state['c10_checkpoints']={'schema':phases.SCHEMA,'phase':'QUERY'}
        self.write_state(state);self.run_step();updated=self.read_state()
        self.assertEqual(updated['category'],'c10_checkpoint_validation_failed')
        self.assertNotIn('suite_receipt',updated);self.assertNotIn('final_receipt',updated['c10_checkpoints'])
        # A real failure without its durable log cannot become a partial receipt.
        self.con.execute('DELETE FROM maintenance_suite_runs')
        self.con.execute('CREATE TABLE frozen_suite_failures(task_id TEXT,output_sha256 TEXT,output TEXT)')
        self.write_state(state)
        self.b.validate_frozen_delivery.side_effect=suite_failure.FrozenSuiteFailure({'output_sha256':'e'*64})
        self.run_step();updated=self.read_state()
        self.assertEqual(updated['category'],'c10_checkpoint_acceptance_failed')
        self.assertNotIn('query_receipt',updated['c10_checkpoints'])
    def test_failed_suite_preserves_failure_and_does_not_dispatch_review(self):
        from broker.suite_failure import FrozenSuiteFailure
        failure={'category':'executed_test_failure','output_sha256':'e'*64}
        self.b.validate_frozen_delivery.side_effect=FrozenSuiteFailure(failure)
        self.run_step();state=self.read_state()
        self.assertEqual(state['stage'],'blocked');self.assertEqual(state['suite_failure'],failure)
        self.assertFalse(state['functional_red']);self.assertFalse(state['delivery_approval'])
    def test_fragment_progress_is_gated_by_durable_full_suite_not_worker_completion(self):
        import hashlib
        from broker.suite_failure import FrozenSuiteFailure
        seed={'task_id':'original','checkpoint':2,'snapshot':{'volume':'old'},'validation':{'test_sha256':'e'*64}}
        state=copy.deepcopy(self.state)
        state.update(functional_correction={'seed':seed,'certificate':{'task_id':'cto'}},
            functional_diagnosis_receipt={'certificate':{'task_id':'cto'},'classification':'DRIVER_OBSERVATION'},
            functional_fragment_recovery={'current':1,'history':[],'original_seed':seed,'attempt_limit_per_fragment':1})
        self.write_state(state)
        output='Ran 259 tests; C10 assertion failure'
        digest=hashlib.sha256(output.encode()).hexdigest()
        self.con.execute('CREATE TABLE frozen_suite_failures(task_id TEXT,output_sha256 TEXT,output TEXT)')
        self.con.execute('INSERT INTO frozen_suite_failures VALUES (?,?,?)',('task',digest,output));self.con.commit()
        failure={'category':'executed_test_failure','tests_executed':259,'source_task':'task','volume':'frozen',
            'exception_types':['AssertionError'],'missing_metadata_keys':[],
            'output_sha256':digest,'failures':[{'kind':'FAIL','test':'test_c10_stale_query_and_status_responses_are_discarded'}]}
        self.b.validate_frozen_delivery.side_effect=FrozenSuiteFailure(failure)
        self.run_step();updated=self.read_state()
        self.assertEqual(updated['stage'],'checkpoint_dispatch_intent')
        self.assertEqual(updated['functional_fragment_recovery']['current'],2)
        self.assertEqual(updated['functional_fragment_recovery']['history'][0]['failure'],failure)
        self.assertEqual(json.loads(self.con.execute('SELECT config FROM test_revision_trials').fetchone()[0])['maintenance_seed']['receipt']['task_id'],'task')
        self.assertEqual(self.con.execute('SELECT status FROM maintenance_suite_runs').fetchone()[0],'failed')
        self.assertFalse(updated['delivery_approval'])
        self.assertNotIn('suite_receipt',updated)
    def test_fragment_does_not_advance_when_c09_is_still_failing(self):
        from broker.suite_failure import FrozenSuiteFailure
        seed={'task_id':'original','checkpoint':2,'snapshot':{'volume':'old'},'validation':{}}
        state=copy.deepcopy(self.state)
        state.update(functional_correction={'seed':seed,'certificate':{}},
            functional_diagnosis_receipt={'certificate':{},'classification':'DRIVER_OBSERVATION'},
            functional_fragment_recovery={'current':1,'history':[],'original_seed':seed,'attempt_limit_per_fragment':1})
        self.write_state(state)
        failure={'category':'executed_test_failure','tests_executed':259,'source_task':'task','volume':'frozen',
            'failures':[{'test':'test_c09_query_survives_polling_and_create_and_complete'}]}
        self.b.validate_frozen_delivery.side_effect=FrozenSuiteFailure(failure)
        self.run_step();updated=self.read_state()
        self.assertEqual(updated['stage'],'blocked');self.assertEqual(updated['functional_fragment_recovery']['current'],1)
    def test_budget_block_is_visible_not_an_unattended_intent(self):
        self.run_step()
        effects=Mock();effects.remaining_calls.return_value=0;effects.ensure_wakeup.return_value=None
        with patch.object(delivery.handoff_runtime,'Effects',return_value=effects):self.run_step()
        self.assertEqual(self.read_state()['category'],'maintenance_review_budget_required')
        self.assertFalse(effects.ensure_wakeup.call_args.kwargs['allow_create'])
    def test_independent_review_qualifies_exact_task_reads_and_manifest(self):
        state=copy.deepcopy(self.state);state['maintenance_review']={'reviewer':'reviewer','wakeup_id':'wake'}
        state['suite_receipt']=delivery.receipt(self.result,state)
        task={'id':'review-task','status':'completed','issue_id':'child','agent_id':'reviewer','wakeup_id':'wake'}
        decision={'action':'approve_test_revision','reason':'Driver runs actual source with preserved tests.',
            'optional_files':[],'manifest_sha256':'a'*64}
        reads={p:{'lines':5,'total_lines':5} for p in delivery.paths()}
        proof=delivery.qualify_review(self.config,state,task,decision,reads)
        self.assertFalse(proof['delivery_approval']);self.assertFalse(proof['functional_red'])
        for changed in (dict(task,agent_id='author'),dict(task,wakeup_id='stale')):
            with self.assertRaises(ValueError):delivery.qualify_review(self.config,state,changed,decision,reads)
        with self.assertRaises(ValueError):delivery.qualify_review(self.config,state,task,dict(decision,manifest_sha256='e'*64),reads)
        with self.assertRaises(ValueError):delivery.qualify_review(self.config,state,task,decision,{})
    def test_review_note_is_bounded_and_never_grants_product_permission(self):
        state=copy.deepcopy(self.state);state['suite_receipt']=delivery.receipt(self.result,state)
        note=delivery.review_note(state)
        self.assertLess(len(note),3900);self.assertIn('missing negative controls and product release remain blocked',note)
        self.assertIn('DELIVERY_TYPED_REVIEW_V1:'+'a'*64,note)
    def test_prompts_delegate_all_execution_to_controller(self):
        from broker.harness_repair_task import checkpoint_note,maintenance_prompt
        note=checkpoint_note(2,{'reason':'actual status observations'})
        self.assertIn('controller executes the complete pinned suite',note)
        prompt=maintenance_prompt('old instructions\nDELIVERY_TEST_ARTIFACT_V1:/workspace/test_new.py\n')
        self.assertIn('executes the full pinned suite on the immutable submission',prompt)
        self.assertNotIn('run only the full pinned suite',prompt)

    def test_guard_restart_preserves_failure_and_revalidates_original_cto_snapshot(self):
        from broker import harness_repair_task as repair
        proof=json.loads((Path(__file__).resolve().parents[1]/'evaluation/SURGICAL-DRIVER-V3-QUALIFICATION-2026-10-04.json').read_text())
        config={**self.config,'file_sha256':{'tests/test_incremental_u3.py':'f'*64}}
        decision={'action':'request_test_revision','reason':'Use staged driver-only repair.','optional_files':[]}
        cto={'id':'cto-task','agent_id':'cto','status':'completed','issue_id':'child','wakeup_id':'diagnosis-wake'}
        reads={p:{'lines':5,'total_lines':5} for p in repair.diagnosis_paths()}
        diagnostic={'issue_id':'child','diagnosis':{'wakeup_id':'diagnosis-wake'},'snapshot':{'volume':'diagnosed-snapshot'},'validation':{'test_sha256':'e'*64}}
        cert=repair.qualify_diagnosis(config,diagnostic,cto,decision,reads)
        state={**self.state,'stage':'blocked','category':'driver_syntax_error','wakeup_id':'failed-wake',
            'diagnosis':diagnostic['diagnosis'],'diagnosis_certificate':cert,'diagnosis_decision':decision,
            'staged':{'current':1,'history':[],'cto_task':'cto-task'}}
        self.write_state(state);self.con.execute('UPDATE harness_repair_tasks SET config=?',(json.dumps(config),))
        self.con.execute('CREATE TABLE leases(status TEXT)');self.con.commit()
        old={'id':'task','agent_id':'author','issue_id':'child','wakeup_id':'failed-wake','status':'completed'}
        fx=Mock();fx.remaining_calls.return_value=86;fx.decision.return_value=decision;fx.read_evidence.return_value=reads
        with tempfile.TemporaryDirectory() as folder:
            self.b.STATE=Path(folder);(self.b.STATE/'native.json').write_text('{}')
            self.b.docker.return_value={'Id':proof['worker_image']}
            with patch.object(repair.handoff_runtime,'Effects',return_value=fx),patch.object(repair.native,'task_record',side_effect=lambda settings,task,agent:cto if task=='cto-task' else old),patch.object(repair.native,'issue_task_runs',return_value=[old]):
                result=repair.arm_driver_guard(self.b,'source',proof)
                self.assertEqual(result['stage'],'checkpoint_dispatch_intent')
                guard=self.read_state()['staged']['driver_guard']
                self.assertEqual(guard['failed_attempt']['snapshot'],state['snapshot'])
                self.assertEqual(guard['origin_task'],'task')
                self.assertTrue(repair.arm_driver_guard(self.b,'source',proof)['reused'])
                with self.assertRaises(ValueError):repair.arm_driver_guard(self.b,'source',dict(proof,uid=0))
