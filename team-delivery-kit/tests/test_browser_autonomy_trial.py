import unittest
from browser_autonomy_trial import derive, fresh_trial, NEW_TEST
from test_portable_contract import contract


class AutonomyTrialTests(unittest.TestCase):
    def template(self):
        value = contract()
        value['schema_version'] = 2
        value['test_roots'] = ['.']
        value['test_command'] = ['python3', '-m', 'unittest', 'discover', '-s', '.', '-q']
        return value

    def test_all_baseline_tests_are_immutable_and_browser_gate_enabled(self):
        tracked = ['AGENTS.md', 'Dockerfile.feedback-bootstrap', 'app/static/app.js',
                   'tests/test_browser_feedback_flow.py', 'tests/test_old.py']
        definition, spec = derive(self.template(), tracked)
        self.assertTrue({'tests/test_browser_feedback_flow.py', 'tests/test_old.py'} <=
                        set(definition['protected_files']))
        self.assertEqual(set(definition['editable_files']), {'app/static/app.js', NEW_TEST})
        self.assertEqual(spec['browser_qa']['scenario'], 'feedback-board-pending-v1')
        self.assertEqual(spec['label'], 'AUTOBROWSER-1')

    def test_existing_new_test_requires_replanning(self):
        with self.assertRaisesRegex(ValueError, 'baseline drift'):
            derive(self.template(), ['tests/test_browser_feedback_flow.py', NEW_TEST])

    def test_fresh_trial_preserves_acceptance_and_immutable_scope(self):
        tracked = ['AGENTS.md', 'Dockerfile.feedback-bootstrap', 'app/static/app.js',
                   'tests/test_browser_feedback_flow.py']
        original_contract, original = derive(self.template(), tracked)
        contract, fresh = fresh_trial(self.template(), tracked)
        self.assertEqual(contract, original_contract)
        self.assertEqual(fresh['browser_qa'], original['browser_qa'])
        self.assertEqual(fresh['review_instruction'], original['review_instruction'])
        self.assertEqual(fresh['label'], 'AUTOBROWSER-2')
        self.assertNotEqual(fresh['qa_host_port'], original['qa_host_port'])
        self.assertTrue(fresh['description'].startswith(original['description']))
        self.assertIn('32768 UTF-8 bytes', fresh['description'])
        self.assertIn('failed POST must not insert', fresh['description'])

    def test_invalid_execution_identity_is_rejected(self):
        with self.assertRaises(ValueError):
            derive(self.template(), ['tests/test_browser_feedback_flow.py'], label='../old')

    def test_revision_ready_execution_keeps_scope_and_requires_distinct_observations(self):
        tracked = ['AGENTS.md', 'Dockerfile.feedback-bootstrap', 'app/static/app.js',
                   'tests/test_browser_feedback_flow.py']
        old_contract, old = fresh_trial(self.template(), tracked)
        definition, spec = fresh_trial(self.template(), tracked, attempt=3)
        self.assertEqual(definition, old_contract)
        self.assertEqual(spec['browser_qa'], old['browser_qa'])
        self.assertEqual(spec['review_instruction'], old['review_instruction'])
        self.assertEqual(spec['label'], 'AUTOBROWSER-3')
        self.assertEqual(spec['qa_host_port'], 19441)
        self.assertIn('DISTINCT observations', spec['description'])
        self.assertIn('controller seeds the prior NEW test', spec['description'])
        with self.assertRaisesRegex(ValueError, 'unsupported'):
            fresh_trial(self.template(), tracked, attempt=4)


if __name__ == '__main__':
    unittest.main()
