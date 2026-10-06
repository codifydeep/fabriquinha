import unittest
from accessible_feedback_trial import derive, NEW_TEST
import test_browser_autonomy_trial as baseline


class AccessibleTrialTests(unittest.TestCase):
    def test_pending_tests_become_protected_regressions(self):
        tracked = ['AGENTS.md', 'Dockerfile.feedback-bootstrap', 'app/static/app.js',
                   'tests/test_browser_feedback_flow.py', 'tests/test_feedback_pending_submit.py']
        contract, spec = derive(baseline.AutonomyTrialTests().template(), tracked)
        self.assertEqual(set(contract['editable_files']), {'app/static/app.js', NEW_TEST})
        self.assertIn('tests/test_feedback_pending_submit.py', contract['protected_files'])
        self.assertEqual(spec['browser_qa']['scenario'], 'feedback-board-pending-accessibility-v1')
        self.assertEqual(spec['qa_host_port'], 19442)
        self.assertIn('ALL 128 baseline tests', spec['description'])
        self.assertIn('No Python tool', spec['review_instruction'])

    def test_old_or_already_used_baseline_rejected(self):
        for tracked in ([], ['tests/test_feedback_pending_submit.py', NEW_TEST]):
            with self.assertRaisesRegex(ValueError, 'baseline drift'):
                derive(baseline.AutonomyTrialTests().template(), tracked)
