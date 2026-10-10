import json
import unittest

from broker.handoff_runtime import Effects


class TechnicalDecisionTests(unittest.TestCase):
    def test_reconsideration_reader_requires_scoped_nonapproving_contract(self):
        decision={'action':'request_review_reconsideration','reason':'Reassess the same delivery',
                  'optional_files':[],'findings':[{'kind':'review_disagreement'}]}
        markers=('DELIVERY_REVIEW_RECONSIDERATION_V1','DELIVERY_TYPED_TEST_DIAGNOSIS_V1','DELIVERY_TEST_FINDINGS_V1')
        task={'handoff_note':'\n'.join(markers)+'\n','result':{'output':json.dumps(decision)}}
        self.assertEqual(self.effects.decision(task),decision)
        for marker in markers:
            with self.assertRaises(ValueError):
                self.effects.decision({**task,'handoff_note':task['handoff_note'].replace(marker,'')})
        for change in ({'optional_files':['tests/anything.py']},{'reason':'x'*1201},
                       {'findings':[]},{'findings':[{'kind':'missing_coverage'}]},
                       {'manifest_sha256':'a'*64},{'action':'approve'}):
            with self.assertRaises(ValueError):
                self.effects.decision({**task,'result':{'output':json.dumps({**decision,**change})}})
    def test_semantic_fields_require_the_controller_policy_marker(self):
        decision = {'action': 'request_test_revision', 'reason': 'Verified string facts.', 'optional_files': [],
                    'experiment_sha256': 'a' * 64,
                    'semantic_checks': [{'fact_index': 0, 'casefold_substring': True}]}
        task = {'handoff_note': 'DELIVERY_SEMANTIC_CHECKS_V1\n', 'result': {'output': json.dumps(decision)}}
        self.assertEqual(self.effects.decision(task), decision)
        with self.assertRaises(ValueError):
            self.effects.decision({'result': task['result']})
    def test_capture_resolution_is_required_only_for_controller_bound_policy(self):
        decision = {'action': 'request_test_revision', 'reason': 'Shared state is incompatible.',
                    'optional_files': [], 'capture_resolutions': []}
        task = {'handoff_note': 'DELIVERY_CAPTURE_CONSTRAINTS_V1\n',
                'result': {'output': json.dumps(decision)}}
        self.assertEqual(self.effects.decision(task), decision)
        with self.assertRaises(ValueError):
            self.effects.decision({'result': task['result']})
    def test_findings_are_allowed_only_for_a_controller_bound_policy_task(self):
        decision = {'action': 'approve_test_revision', 'reason': 'Verified.', 'findings': [],
                    'optional_files': [], 'manifest_sha256': 'a'*64}
        task = {'handoff_note': 'Instruction:\nDELIVERY_TEST_FINDINGS_V1\n',
                'result': {'output': json.dumps(decision)}}
        self.assertEqual(self.effects.decision(task), decision)
        with self.assertRaises(ValueError):
            self.effects.decision({'result': task['result']})
        task['result']['output'] = json.dumps({k: v for k, v in decision.items() if k != 'findings'})
        with self.assertRaises(ValueError):
            self.effects.decision(task)

    def test_independent_test_approval_requires_exact_snapshot_field(self):
        decision = {'action': 'approve_test_revision', 'reason': 'Verified the new harness.',
                    'optional_files': [], 'manifest_sha256': 'a' * 64}
        self.assertEqual(self.effects.decision({'result': {'output': json.dumps(decision)}}), decision)
        with self.assertRaises(ValueError):
            self.effects.decision({'result': {'output': json.dumps(
                {**decision, 'manifest_sha256': 'old'})}})
    def test_test_revision_proposal_is_not_contract_relaxation(self):
        decision = {'action': 'request_test_revision', 'reason': 'Mock DOM is incorrect.',
                    'optional_files': []}
        self.assertEqual(self.effects.decision({'result': {'output': json.dumps(decision)}}), decision)
        with self.assertRaisesRegex(ValueError, 'cannot relax'):
            self.effects.decision({'result': {'output': json.dumps(
                {**decision, 'optional_files': ['tests/test_new.py']})}})

    def setUp(self):
        self.effects = Effects(None, {})

    def test_completed_task_result_accepts_detailed_correction(self):
        decision = {'action': 'request_correction', 'reason': 'A' * 1400,
                    'optional_files': []}
        task = {'id': 'task', 'result': {'output': json.dumps(decision)}}
        self.assertEqual(self.effects.decision(task), decision)

    def test_single_json_code_fence_is_accepted(self):
        decision = {'action': 'request_correction', 'reason': 'Retry the failed execution.',
                    'optional_files': []}
        task = {'id': 'task', 'result': {'output': '```json\n' + json.dumps(decision) + '\n```'}}
        self.assertEqual(self.effects.decision(task), decision)

    def test_extra_text_outside_fence_is_rejected(self):
        task = {'id': 'task', 'result': {'output': 'Explanation\n```json\n{}\n```'}}
        with self.assertRaises(ValueError):
            self.effects.decision(task)

    def test_large_or_unstructured_decision_is_rejected(self):
        for decision in (
                {'action': 'request_correction', 'reason': 'A' * 3001, 'optional_files': []},
                {'action': 'approve', 'reason': 'looks good', 'optional_files': []}):
            with self.subTest(decision=decision['action']), self.assertRaises(ValueError):
                self.effects.decision({'id': 'task', 'result': {'output': json.dumps(decision)}})


if __name__ == '__main__':
    unittest.main()
