import json
from pathlib import Path
import unittest

from browser_feedback_recovery_trial import derive, NEW_TEST


class BrowserRecoveryIntakeTests(unittest.TestCase):
    def template(self):
        root = Path(__file__).resolve().parents[1]
        return json.loads((root / 'projects/descartavel2-summary-slice-v2-ui.contract.json').read_text())

    def test_freezes_every_old_test_and_preserves_qa(self):
        template = self.template()
        contract, spec = derive(template, template['files'])
        self.assertTrue(set(template['test_files']) <= set(contract['protected_files']))
        self.assertEqual(contract['editable_files'], ['app/static/app.js', NEW_TEST])
        self.assertEqual(contract['qa_cases'], template['qa_cases'])
        self.assertEqual(contract['test_command'], template['test_command'])
        self.assertIn('Window.status', spec['description'])
        self.assertIn('NOT proof of a real browser', spec['description'])

    def test_rejects_reusing_regression_name_or_missing_frozen_ui_test(self):
        template = self.template()
        with self.assertRaisesRegex(ValueError, 'baseline drift'):
            derive(template, template['files'] + [NEW_TEST])
        with self.assertRaisesRegex(ValueError, 'baseline drift'):
            derive(template, set(template['files']) - {'tests/test_feedback_summary_ui.py'})
