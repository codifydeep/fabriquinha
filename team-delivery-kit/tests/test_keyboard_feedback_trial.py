import unittest
from keyboard_feedback_trial import derive, NEW_TEST
import test_browser_autonomy_trial as baseline


class KeyboardTrialTests(unittest.TestCase):
    def test_entire_previous_accessibility_suite_is_protected(self):
        tracked = ['AGENTS.md', 'Dockerfile.feedback-bootstrap', 'app/static/app.js',
                   'tests/test_feedback_busy_accessibility.py', 'tests/test_feedback_pending_submit.py']
        contract, spec = derive(baseline.AutonomyTrialTests().template(),tracked)
        self.assertEqual(set(contract['editable_files']),{'app/static/app.js',NEW_TEST})
        self.assertTrue(set(tracked[3:]) <= set(contract['protected_files']))
        self.assertEqual(spec['browser_qa']['scenario'],'feedback-board-keyboard-dismiss-v1')
        self.assertEqual(spec['qa_host_port'],19443)
        self.assertIn('138 baseline tests',spec['description'])
        self.assertIn('controller offline Docker runner',spec['review_instruction'])

    def test_old_or_previously_used_baseline_rejected(self):
        for tracked in ([], ['tests/test_feedback_busy_accessibility.py',NEW_TEST]):
            with self.assertRaisesRegex(ValueError,'baseline drift'):
                derive(baseline.AutonomyTrialTests().template(),tracked)
