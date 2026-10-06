import copy
import json
from pathlib import Path
import unittest

from planned_delivery import derive


ROOT = Path(__file__).resolve().parents[1]


class PlannedDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.template = json.loads((ROOT / 'projects/descartavel2-autoloss-3.contract.json').read_text())
        self.run = json.loads((ROOT / 'projects/descartavel2-autoloss-3.run.json').read_text())
        self.tracked = self.template['files']
        command = ['python3', '-m', 'unittest', 'discover', '-s', '.', '-q']
        self.plan = {'role': 'techlead', 'integration_order': ['C1', 'C2'], 'cards': [
            {'id': 'C1', 'owner': 'backend_data', 'title': 'New API', 'depends_on': [],
             'acceptance': ['New API behavior'], 'test_command': command,
             'files': ['app/server.py', 'tests/test_new_api.py']},
            {'id': 'C2', 'owner': 'frontend', 'title': 'New UI', 'depends_on': ['C1'],
             'acceptance': ['New UI behavior'], 'test_command': command,
             'files': ['app/static/app.js', 'tests/test_new_ui.py']}]}
        self.stages = []
        for index, owner in enumerate(('backend', 'frontend')):
            template = copy.deepcopy(self.template)
            template['editable_files'] = [self.plan['cards'][index]['files'][0], 'tests/test_template.py']
            run = {**self.run, 'label': ('NEWAPI-1', 'NEWUI-1')[index],
                   'qa_host_port': 19500 + index,
                   'implementer_registry': 'pilot-' + owner + ('-data' if index == 0 else '') + '.json'}
            self.stages.append({'contract': template, 'spec': run})
        self.cto = {'role': 'cto', 'stack': 'Keep Python and vanilla JS',
                    'components': ['API', 'UI'], 'security': ['No secrets'],
                    'technical_decisions': ['Keep existing API contracts'], 'risks': []}

    def derive(self):
        return derive(self.plan, self.tracked, self.stages, 'Approved CEO request.',
                      self.cto, name='NEW-1', prefix='new-1', project_config='descartavel2.json')

    def test_uses_agent_scopes_and_operator_qa_without_historical_filter_identity(self):
        outputs = self.derive()
        first, second = outputs['new-1-c1.contract.json'], outputs['new-1-c2.contract.json']
        self.assertEqual(first['editable_files'], sorted(self.plan['cards'][0]['files']))
        self.assertEqual(second['editable_files'], sorted(self.plan['cards'][1]['files']))
        self.assertIn('tests/test_new_api.py', second['protected_files'])
        self.assertIn('tests/test_autoloss_livecheck.py', first['protected_files'])
        self.assertEqual(first['qa_cases'], self.template['qa_cases'])
        self.assertEqual(outputs['new-1-c2.run.json']['browser_qa'], self.run['browser_qa'])
        self.assertEqual(outputs['new-1.sequence.json']['stages'][1]['depends_on'], 'NEWAPI-1')
        self.assertIn('Keep existing API contracts', outputs['new-1-c1.run.json']['description'])
        self.assertNotIn('FILTER-1', json.dumps(outputs))
        self.assertIn('DELIVERY_TYPED_TEST_SOURCE_V1', outputs['new-1-c1.run.json']['description'])

    def test_fails_closed_on_code_outside_preapproved_template(self):
        self.plan['cards'][0]['files'].append('app/store.py')
        with self.assertRaisesRegex(ValueError, 'preapproved'):
            self.derive()

    def test_generated_brief_must_fit_normal_worker_limit_before_dispatch(self):
        with self.assertRaisesRegex(ValueError, 'context'):
            derive(self.plan, self.tracked, self.stages, 'x' * 3600, self.cto,
                   name='NEW-1', prefix='new-1', project_config='descartavel2.json')

    def test_cannot_edit_baseline_tests_or_predecessor_test(self):
        for path in ('tests/test_autoloss_livecheck.py', 'tests/test_new_api.py'):
            with self.subTest(path=path):
                plan = copy.deepcopy(self.plan)
                self.plan['cards'][1]['files'].append(path)
                with self.assertRaisesRegex(ValueError, 'frozen'):
                    self.derive()
                self.plan = plan

    def test_rejects_wrong_owner_duplicate_ports_and_repository(self):
        self.stages[1]['spec']['implementer_registry'] = 'pilot-backend-data.json'
        with self.assertRaisesRegex(ValueError, 'owner'):
            self.derive()
        self.stages[1]['spec']['implementer_registry'] = 'pilot-frontend.json'
        self.stages[1]['spec']['qa_host_port'] = self.stages[0]['spec']['qa_host_port']
        with self.assertRaisesRegex(ValueError, 'identities'):
            self.derive()
        self.stages[1]['spec']['qa_host_port'] += 1
        self.stages[1]['contract']['repository'] = 'other/repository'
        with self.assertRaisesRegex(ValueError, 'repository'):
            self.derive()

    def test_requires_cto_proposal_and_exact_two_card_plan(self):
        self.cto['role'] = 'product'
        with self.assertRaises(ValueError):
            self.derive()

    def test_rejects_path_escape_and_excessive_context(self):
        with self.assertRaises(ValueError):
            derive(self.plan, self.tracked, self.stages, 'Brief', self.cto,
                   name='NEW-1', prefix='../escape', project_config='descartavel2.json')
        with self.assertRaisesRegex(ValueError, 'context'):
            derive(self.plan, self.tracked, self.stages, 'x' * 20000, self.cto,
                   name='NEW-1', prefix='new-1', project_config='descartavel2.json')
