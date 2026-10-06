import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from dependent_sequence import load_plan, resume_verified_test_correction


class TestCorrectionSupervisionTests(unittest.TestCase):
    def test_fault_resolves_only_after_verified_delivery_and_history_is_kept(self):
        from dependent_sequence import resolve_delivered_incident
        from unittest.mock import patch
        ledger={**self.ledger,'stage':'done','active':None,'completed':[
            s['spec']['label'] for s in self.plan['stages']],
            'recovery_supervision':[dict(status='supervision_resumed_not_delivered')]}
        receipt={**self.receipt,'pr_url':'https://github.com/example/repo/pull/1'}
        original=copy.deepcopy(ledger)
        with patch('dependent_sequence.receipt_identity',return_value=True):
            result=resolve_delivered_incident(ledger,self.stage,receipt,verify=self.verify)
            self.assertNotIn('category',result)
            self.assertEqual(result['resolved_incidents'][0]['category'],ledger['category'])
            self.assertEqual(result['recovery_supervision'],ledger['recovery_supervision'])
            self.assertEqual(ledger,original)
            self.assertIs(resolve_delivered_incident(result,self.stage,receipt,verify=self.verify),result)
            with self.assertRaises(ValueError):
                resolve_delivered_incident({**ledger,'stage':'working'},self.stage,receipt,verify=self.verify)
            self.verify.side_effect=ValueError('QA unavailable')
            with self.assertRaisesRegex(ValueError,'QA unavailable'):
                resolve_delivered_incident(ledger,self.stage,receipt,verify=self.verify)
            self.assertEqual(ledger,original)
    def test_review_context_resume_requires_durable_presentation_and_independent_cto(self):
        from dependent_sequence import resume_verified_review_context
        from unittest.mock import patch
        self.ledger['category']='RuntimeError:technical_decision_required:recipient_execution_failed'
        proof=dict(issue_id='frontend',enabled=True,contract_sha256=self.context['contract_sha256'],qualified=True,
            approval=False,stage='accepted',source_task='source',source_status='completed',source_agent='author',
            author='author',reviewer='reviewer',cto='cto',review_retries=1,baseline_tests_intact=True,
            request=dict(issue_id='frontend',source_task='source',failed_review='old-review'),
            cto_task='cto-decision',cto_status='completed',cto_agent='cto',cto_wakeup='cto-wake',
            used=dict(cto_task='cto-decision',cto_wakeup='cto-wake',decision=dict(action='retry_review',optional_files=[])),
            review_task='new-review',review_agent='reviewer',review_status='running',review_wakeup='new-wake',wakeup='new-wake',
            manifest_sha256='b'*64,presentation=dict(operation='registered_review_presentation_v1',approval=False,
                source_task='source',issue_id='frontend',wakeup_id='new-wake',manifest_sha256='b'*64))
        def run():
            with patch('dependent_sequence.receipt_identity',return_value=True):
                return resume_verified_review_context(self.ledger,self.plan,self.root,read_proof=lambda _:proof,
                    read_delivery=lambda *_:self.receipt,verify=self.verify,verify_ci=self.ci)
        resumed=run();self.assertEqual(resumed['stage'],'working');self.assertEqual(resumed['completed'],self.ledger['completed'])
        self.assertEqual(resumed['category'],self.ledger['category']);self.assertNotIn('resolved_incidents',resumed)
        for key,value in [('qualified',False),('review_task','old-review'),('cto_status','running'),
                          ('review_status','failed'),('presentation',{}),('review_retries',0)]:
            old=proof[key];proof[key]=value;self.assertIsNone(run());proof[key]=old
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.plan = load_plan(Path(__file__).resolve().parents[1] /
                              'projects/descartavel2-search-1.sequence.json')
        self.stage = self.plan['stages'][1]
        self.label = self.stage['spec']['label']
        self.context = {'issue_id': 'frontend', 'label': self.label,
            'durable_handoffs': True, 'base_sha': 'a' * 40,
            'contract_sha256': hashlib.sha256(json.dumps(self.stage['contract'],
                sort_keys=True, separators=(',', ':')).encode()).hexdigest()}
        (self.root / ('portable-context-' + self.label + '.json')).write_text(json.dumps(self.context))
        self.ledger = {'stage': 'blocked', 'plan_sha256': self.plan['sha256'],
            'active': self.label, 'completed': [self.plan['stages'][0]['spec']['label']],
            'issues': {self.label: 'frontend'}, 'category':
                'RuntimeError:technical_decision_required:ValueError:test-first snapshot rejected'}
        self.proof = {'issue_id': 'frontend', 'enabled': True, 'test_first': True,
            'author': 'author', 'cto': 'cto', 'latest_stage': 'test_author_active',
            'source_task': 'source', 'source_agent': 'author', 'source_status': 'completed',
            'cto_task': 'diagnosis', 'cto_agent': 'cto', 'cto_status': 'completed',
            'decision': {'action': 'request_correction', 'reason': 'Write the missing tests.', 'optional_files': []},
            'diagnostic': {'kind': 'rejected_snapshot', 'category': 'empty_new_test',
                'issue_id': 'frontend', 'task_id': 'source',
                'files': {'tests/test_feedback_search_client.py': {'bytes': 0,
                    'sha256': hashlib.sha256(b'').hexdigest()}}},
            'correction_task': 'corrected', 'correction_status': 'running', 'wakeup': 'bound-wakeup'}
        self.receipt = {'merge_sha': 'a' * 40}
        self.verify = Mock()
        self.ci = Mock()

    def run_resume(self):
        from unittest.mock import patch
        with patch('dependent_sequence.receipt_identity', return_value=True):
            return resume_verified_test_correction(self.ledger, self.plan, self.root,
                read_proof=lambda _: self.proof, read_delivery=lambda *_: self.receipt,
                verify=self.verify, verify_ci=self.ci)

    def test_resumes_existing_supervision_without_completing_or_resolving_incident(self):
        original = copy.deepcopy(self.ledger)
        resumed = self.run_resume()
        self.assertEqual(resumed['stage'], 'working')
        self.assertEqual(resumed['completed'], original['completed'])
        self.assertEqual(resumed['category'], original['category'])
        self.assertNotIn('resolved_incidents', resumed)
        self.assertEqual(resumed['recovery_supervision'][0]['correction_task'], 'corrected')
        self.assertEqual(self.ledger, original)
        self.verify.assert_called_once()
        self.ci.assert_called_once()

    def test_failed_same_or_unrelated_worker_cannot_resume(self):
        for key, value in [('correction_status', 'failed'), ('correction_task', 'source'),
                           ('issue_id', 'other'), ('source_agent', 'cto'),
                           ('latest_stage', 'test_first_blocked'), ('enabled', False)]:
            with self.subTest(key=key):
                old = self.proof[key]
                self.proof[key] = value
                self.assertIsNone(self.run_resume())
                self.proof[key] = old
        self.verify.assert_not_called()

    def test_no_decision_authority_or_stale_base_cannot_resume(self):
        self.proof['decision']['action'] = 'escalate_cto'
        self.assertIsNone(self.run_resume())
        self.proof['decision']['action'] = 'request_correction'
        self.receipt['merge_sha'] = 'b' * 40
        self.assertIsNone(self.run_resume())
        self.verify.assert_not_called()

    def test_ci_outage_preserves_blocked_ledger(self):
        original = copy.deepcopy(self.ledger)
        self.ci.side_effect = ValueError('CI unavailable')
        with self.assertRaisesRegex(ValueError, 'CI unavailable'):
            self.run_resume()
        self.assertEqual(self.ledger, original)

    def test_context_repair_supervises_only_real_cto_correction_after_qualified_preservation(self):
        from generated_context import START, END, compact
        self.stage['spec']['description']='Acceptance\nApproved CEO request: '+'x'*3300+'\nBinding CTO proposal: unchanged\n'+START+'["test_new.py"]'+END
        _, presentation=compact(self.stage['spec']['description'])
        self.ledger['category']='RuntimeError:test_first_blocked:test_first_cto_requires_replanning'
        self.proof['source_status']='failed'
        self.proof['source_error']='restricted broker stream failed: native_prompt_bounds'
        self.proof['diagnostic']={'kind':'preserved_pretool_infrastructure','category':'native_prompt_bounds',
            'issue_id':'frontend','task_id':'source','baseline_unchanged':True,'accepted_tools':0,'new_test_empty':True}
        self.proof['infrastructure_contract']={'qualified':True,
            'operation':'preserved_pretool_infrastructure_diagnosis_v1',
            'request':{'issue_id':'frontend','source_task':'source','cto_task':'old-diagnosis'},
            'proof':{'verified':True,'baseline_unchanged':True,'manifest_sha256':'b'*64},
            'prompt_presentation':presentation,'author_retry_authorized':False}
        resumed=self.run_resume()
        self.assertEqual(resumed['stage'],'working')
        self.assertEqual(resumed['completed'],self.ledger['completed'])
        self.proof['infrastructure_contract']['qualified']=False
        self.assertIsNone(self.run_resume())

    def test_empty_test_recovery_requires_new_bound_artifact_contract(self):
        self.ledger['category'] = 'RuntimeError:technical_decision_required:ValueError:test-first NEW test is empty'
        self.assertIsNone(self.run_resume())
        self.proof['latest_stage'] = 'test_first_artifact_recovery_wait'
        self.proof['artifact_contract'] = {'contract': 'observed-source-read-verified-test-write-v1',
            'contract_sha256': 'c' * 64, 'request': {'issue_id': 'frontend', 'source_task': 'source',
                'cto_task': 'diagnosis', 'worker_image': 'sha256:' + 'd' * 64}}
        self.assertEqual(self.run_resume()['stage'], 'working')
        self.proof['artifact_contract']['request']['source_task'] = 'other'
        self.assertIsNone(self.run_resume())

    def test_nonempty_no_methods_recovery_requires_exact_structural_receipt(self):
        self.ledger['category'] = 'RuntimeError:technical_decision_required:ValueError:test-first NEW test has no executable test methods'
        self.proof['diagnostic']['category'] = 'new_test_no_methods'
        self.proof['diagnostic']['files'] = {'tests/test_feedback_search_client.py':{'bytes':1754,'sha256':'b'*64}}
        self.assertIsNone(self.run_resume())
        self.proof['structural_contract'] = {'kind':'nonempty_no_methods_cto_replan_v1',
            'request':{'issue_id':'frontend','source_task':'source','worker_image':'sha256:'+'d'*64},
            'diagnostic_sha256':hashlib.sha256(json.dumps(self.proof['diagnostic'],sort_keys=True).encode()).hexdigest()}
        self.assertEqual(self.run_resume()['stage'],'working')
        self.proof['diagnostic']['files']['tests/test_feedback_search_client.py']['bytes'] = 1755
        self.assertIsNone(self.run_resume())

    def test_acp_recovery_requires_bound_real_artifact_and_preserved_diagnostic(self):
        from model_policy import MODEL
        self.ledger['category'] = 'RuntimeError:technical_decision_required:ValueError:test-first NEW test has no executable test methods'
        self.proof['diagnostic']['category'] = 'new_test_no_methods'
        self.proof['diagnostic']['files'] = {'tests/test_feedback_search_client.py':{'bytes':1754,'sha256':'b'*64}}
        self.proof['latest_stage'] = 'test_first_transport_recovery_wait'
        probe = dict(schema='acp-artifact-probe-v1', status='passed', model=MODEL,
            worker_image='sha256:'+'a'*64, proxy_image='sha256:'+'b'*64,
            execution_id='11111111-1111-4111-8111-111111111111', delivery_approval=False,
            product_retry=False, prompt_completed=True, fixture_removed=True,
            inspection=dict(uid=10000, syntax_valid=True, baseline_unchanged=True,
                            credentials_absent=True, bytes=196, test_methods=1, sha256='c'*64))
        self.proof['transport_contract'] = {'kind':'qualified_acp_response_enforcement_v1',
            'request':{'issue_id':'frontend','source_task':'source','probe':probe},
            'diagnostic_sha256':hashlib.sha256(json.dumps(self.proof['diagnostic'],sort_keys=True).encode()).hexdigest()}
        self.assertEqual(self.run_resume()['stage'], 'working')
        probe['inspection']['bytes'] = 0
        self.assertIsNone(self.run_resume())
        probe['inspection']['bytes'] = 196
        self.proof['transport_contract']['diagnostic_sha256'] = 'd'*64
        self.assertIsNone(self.run_resume())

    def test_pretool_integration_resumes_original_diagnostic_not_failed_artifact(self):
        from model_policy import MODEL
        self.ledger['category']='RuntimeError:technical_decision_required:ValueError:test-first NEW test has no executable test methods'
        self.proof['diagnostic']['category']='new_test_no_methods'
        self.proof['diagnostic']['files']={'tests/test_feedback_search_client.py':{'bytes':1754,'sha256':'b'*64}}
        self.proof['latest_stage']='test_first_integration_recovery_wait'
        self.proof['transport_contract']={'kind':'qualified_acp_response_enforcement_v1',
            'repair_kind':'pre_tool_read_schema_repair_v1','original_source':'source','pretool_verified':True,
            'request':{'issue_id':'frontend','source_task':'11111111-1111-4111-8111-111111111111','probe':{
                'schema':'acp-artifact-probe-v1','status':'passed','model':MODEL,'worker_image':'sha256:'+'a'*64,
                'proxy_image':'sha256:'+'b'*64,'execution_id':'22222222-2222-4222-8222-222222222222',
                'delivery_approval':False,'product_retry':False,'prompt_completed':True,'fixture_removed':True,
                'inspection':{'uid':10000,'bytes':196,'test_methods':1,'syntax_valid':True,'baseline_unchanged':True,'credentials_absent':True,'sha256':'c'*64}}},
            'diagnostic_sha256':hashlib.sha256(json.dumps(self.proof['diagnostic'],sort_keys=True).encode()).hexdigest()}
        self.assertEqual(self.run_resume()['stage'],'working')
        self.proof['transport_contract']['pretool_verified']=False
        self.assertIsNone(self.run_resume())

    def test_postread_replan_requires_distinct_activity_and_preserved_snapshot(self):
        self.test_pretool_integration_resumes_original_diagnostic_not_failed_artifact()
        contract=self.proof['transport_contract']; request=contract['request']
        contract.update(repair_kind='post_read_compact_write_replan_v1',postread_verified=True,
            recovery_policy={'first_write_max_characters':6144,'incremental_full_coverage':True,
                             'truncation_proven':False,'same_class_attempt_limit':1},
            activity={'write_file_call_count':0,'tool_result_counts':{'read_file:read_returned':11}},
            failed_snapshot={'verified':True,'baseline_unchanged':True,'task_id':request['source_task']})
        request['failure']={'selected_tool':'write_file','completion_tokens':8192,'output_limit':8192}
        self.ledger['category']='RuntimeError:test_first_blocked:test_first_correction_failed_after_cto_diagnosis'
        self.assertEqual(self.run_resume()['stage'],'working')
        for section,key,value in [('activity','write_file_call_count',1),
                                  ('failed_snapshot','baseline_unchanged',False),
                                  ('recovery_policy','incremental_full_coverage',False)]:
            original=contract[section][key];contract[section][key]=value
            self.assertIsNone(self.run_resume());contract[section][key]=original
        contract['pretool_verified']=True
        self.assertIsNone(self.run_resume())

    def test_exhausted_correction_is_not_resumed_by_generic_running_worker(self):
        self.ledger['category']='RuntimeError:test_first_blocked:test_first_correction_failed_after_cto_diagnosis'
        self.assertIsNone(self.run_resume())
        self.verify.assert_not_called()


if __name__ == '__main__':
    unittest.main()
