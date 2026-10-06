import json
from pathlib import Path
import unittest
from compile_planned_sequence import derive


class CompilePlanTests(unittest.TestCase):
    def setUp(self):
        self.template = json.loads((Path(__file__).parents[1] / 'projects/descartavel2-keyboard-1.contract.json').read_text())
        self.tracked = self.template['files']
        command = ['python3', '-m', 'unittest', 'discover', '-s', '.', '-q']
        self.plan = {'cards': [
            {'id': 'C1', 'owner': 'backend_data', 'title': 'API filter', 'depends_on': [],
             'acceptance': ['HTTP filtering passes'], 'test_command': command,
             'files': ['app/server.py', 'tests/test_new_filter_api.py']},
            {'id': 'C2', 'owner': 'frontend', 'title': 'Browser filter', 'depends_on': ['C1'],
             'acceptance': ['Two browser filtering passes'], 'test_command': command,
             'files': ['app/static/app.js', 'tests/test_new_filter_ui.py']}]}
        self.resolution = {'parameter': 'status', 'absent': 'all', 'empty': '400',
                           'explicit_all': '400', 'unknown': '400'}

    def derive(self):
        return derive(self.plan, self.tracked, self.template, 'All approved user behavior.',
                      self.resolution, 'sha256:' + 'b' * 64)

    def test_generated_scopes_are_exactly_agent_owned_and_freeze_prior_tests(self):
        result = self.derive()
        api = result['descartavel2-filter-1-api.contract.json']
        ui = result['descartavel2-filter-1-ui.contract.json']
        self.assertEqual(set(api['editable_files']), set(self.plan['cards'][0]['files']))
        self.assertEqual(set(ui['editable_files']), set(self.plan['cards'][1]['files']))
        self.assertIn('tests/test_new_filter_api.py', ui['protected_files'])
        self.assertIn('tests/test_feedback_keyboard_dismiss.py', api['protected_files'])
        self.assertEqual(result['descartavel2-filter-1.sequence.json']['stages'][1]['depends_on'], 'FILTERAPI-1')
        self.assertEqual(result['descartavel2-filter-1-ui.run.json']['browser_qa']['scenario'], 'feedback-board-filter-v1')

    def test_cto_decision_cannot_silently_use_incompatible_browser_qa(self):
        self.resolution['empty'] = 'all'
        with self.assertRaisesRegex(ValueError, 'another independently qualified'):
            self.derive()

    def test_agent_cannot_gain_governance_or_infrastructure_writes(self):
        self.plan['cards'][0]['files'].append('AGENTS.md')
        with self.assertRaisesRegex(ValueError, 'outside qualified'):
            self.derive()
