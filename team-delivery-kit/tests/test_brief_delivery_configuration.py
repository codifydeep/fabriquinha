import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import dependent_sequence
import planning_intake
from planned_delivery import load_configuration


ROOT = Path(__file__).resolve().parents[1]


class BriefDeliveryConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.projects = self.root / 'projects'
        self.projects.mkdir()
        self.config = {'name': 'NEW-1', 'prefix': 'new-1', 'project_config': 'repo.json',
                       'planning_config': 'new-1.planning.json', 'minimum_calls': 256,
                       'stages': [{'contract': 'api.contract.json', 'run_spec': 'api.run.json'},
                                  {'contract': 'ui.contract.json', 'run_spec': 'ui.run.json'}]}
        self.save('repo.json', {'repository': 'codifydeep/descartavel2', 'checkout': 'sandbox-github2'})
        self.save('new-1.planning.json', {'name': 'NEW-1', 'brief': 'new-1.brief.md',
                                        'minimum_calls': 64, 'base_sha': 'a' * 40})
        self.body='## CEO request\n\n'+('Approved concrete acceptance. '*8)+'\n\n## Team authority\nTechnical decisions delegated.'
        (self.projects / 'new-1.brief.md').write_text(self.body)
        self.template = json.loads((ROOT / 'projects/descartavel2-autoloss-3.contract.json').read_text())
        run = json.loads((ROOT / 'projects/descartavel2-autoloss-3.run.json').read_text())
        for index, name in enumerate(('api', 'ui')):
            self.save(name + '.contract.json', self.template)
            self.save(name + '.run.json', {**run, 'label': ('NEWAPI-1', 'NEWUI-1')[index],
                                          'qa_host_port': 19500 + index})
        self.path = self.projects / 'new-1.delivery.json'
        self.save(self.path.name, self.config)

    def save(self, name, data):
        (self.projects / name).write_text(json.dumps(data))

    def read(self):
        with patch.object(dependent_sequence, 'PROJECTS', self.projects), \
                patch.object(planning_intake, 'ROOT', self.root):
            return load_configuration(self.path)

    def test_hash_binds_actual_templates_brief_and_project_not_just_names(self):
        first = self.read()
        self.assertEqual(first['selection']['base_sha'], 'a' * 40)
        (self.projects / 'new-1.brief.md').write_text(self.body.replace('concrete','changed concrete'))
        self.assertNotEqual(first['sha256'], self.read()['sha256'])
        second = self.read()
        modified = copy.deepcopy(self.template)
        modified['qa_cases'].append({'path': '/livecheck?test=1', 'status': 200,
                                     'expected_json': {'status': 'ok'}, 'bind_source_sha': False})
        self.save('api.contract.json', modified)
        self.assertNotEqual(second['sha256'], self.read()['sha256'])

    def test_no_shell_or_foreign_template_selection(self):
        self.config['stages'][0]['contract'] = '../foreign.json'
        self.save(self.path.name, self.config)
        with self.assertRaises(ValueError):
            self.read()

    def test_invalid_brief_fails_at_configuration_before_native_registration(self):
        (self.projects / 'new-1.brief.md').write_text('Missing required request boundaries.')
        with self.assertRaisesRegex(ValueError,'unambiguous'):
            self.read()

    def test_rejects_unapproved_reserve_and_unknown_fields(self):
        for key, value in (('minimum_calls', 255), ('minimum_calls', True), ('command', 'shell')):
            original = copy.deepcopy(self.config)
            self.config[key] = value
            self.save(self.path.name, self.config)
            with self.assertRaises(ValueError):
                self.read()
            self.config = original

    def test_cannot_reuse_other_planning_run_or_repository(self):
        self.save('new-1.planning.json', {'name': 'OLD-1', 'brief': 'new-1.brief.md',
                                        'minimum_calls': 64, 'base_sha': 'a' * 40})
        with self.assertRaisesRegex(ValueError, 'identity'):
            self.read()

    def test_symlink_input_is_rejected(self):
        (self.projects / 'api.contract.json').unlink()
        (self.projects / 'api.contract.json').symlink_to(self.projects / 'ui.contract.json')
        with self.assertRaises(ValueError):
            self.read()

    def test_browser_qa_is_required_not_optional(self):
        run = json.loads((self.projects / 'api.run.json').read_text())
        run.pop('browser_qa')
        self.save('api.run.json', run)
        with self.assertRaisesRegex(ValueError, 'browser'):
            self.read()
