import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import planning_intake as planning


class PlanningConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.projects = self.root / 'projects'
        self.projects.mkdir()
        self.brief = self.projects / 'filter-1.brief.md'
        self.brief.write_text('## CEO request\n\n'+('Disposable concrete acceptance. '*8)+'\n\n## Team authority\nTechnical decisions delegated.')
        self.path = self.projects / 'filter-1.planning.json'
        self.config = {'name': 'FILTER-1', 'brief': self.brief.name,
                       'minimum_calls': 192, 'base_sha': 'a' * 40}
        self.save()

    def save(self):
        self.path.write_text(json.dumps(self.config))

    def read(self):
        with patch.object(planning, 'ROOT', self.root):
            return planning.intake_configuration(self.path)

    def test_pins_new_run_brief_base_budget_and_config_digest(self):
        result = self.read()
        self.assertEqual(result['name'], 'FILTER-1')
        self.assertEqual(result['brief'], self.brief)
        self.assertEqual(result['base_sha'], 'a' * 40)
        self.assertEqual(result['minimum_calls'], 192)
        self.assertEqual(result['configuration_sha256'], hashlib.sha256(self.path.read_bytes()).hexdigest())

    def test_rejects_traversal_and_foreign_files(self):
        for name in ('../filter-1.brief.md', '/etc/passwd', '.env', 'filter-1.json'):
            self.config['brief'] = name
            self.save()
            with self.assertRaises(ValueError):
                self.read()

    def test_rejects_symlink_config_and_brief(self):
        link = self.projects / 'link.json'
        link.symlink_to(self.path)
        with patch.object(planning, 'ROOT', self.root), self.assertRaises(ValueError):
            planning.intake_configuration(link)
        self.brief.unlink()
        self.brief.symlink_to(self.path)
        with self.assertRaises(ValueError):
            self.read()

    def test_rejects_unsafe_identity_budget_and_sha(self):
        for field, value in (('name', '../OLD'), ('minimum_calls', True),
                             ('minimum_calls', 63), ('minimum_calls', 513),
                             ('base_sha', 'main'), ('base_sha', 'A' * 40)):
            original = self.config[field]
            self.config[field] = value
            self.save()
            with self.assertRaises(ValueError):
                self.read()
            self.config[field] = original

    def test_rejects_unknown_configuration_fields(self):
        self.config['command'] = 'anything'
        self.save()
        with self.assertRaises(ValueError):
            self.read()

    def test_default_preserves_legacy_run_without_environment(self):
        with patch.dict('os.environ', {}, clear=True):
            result = planning.intake_configuration()
        self.assertEqual(result['name'], planning.NAME)
        self.assertEqual(result['brief'], planning.BRIEF)
        self.assertEqual(result['minimum_calls'], 64)
        self.assertIsNone(result['configuration_sha256'])

    def test_dispatch_plan_requires_discoverable_new_tests_for_both_cards(self):
        command = ['python3', '-m', 'unittest', 'discover', '-s', '.', '-q']
        proposal = {'cards': [
            {'id': 'C1', 'owner': 'backend_data', 'depends_on': [],
             'test_command': command, 'files': ['app/server.py', 'test_filter_api.py']},
            {'id': 'C2', 'owner': 'frontend', 'depends_on': ['C1'],
             'test_command': command, 'files': ['app/static/app.js', 'tests/test_filter_ui.py']}]}
        tracked = ['app/server.py', 'app/static/app.js', 'tests/test_old.py']
        self.assertEqual(planning.validate_execution_plan(proposal, tracked), proposal)
        proposal['cards'][0]['files'][1] = 'feedback_tests_filter_api.py'
        with self.assertRaisesRegex(ValueError, 'discoverable'):
            planning.validate_execution_plan(proposal, tracked)
        proposal['cards'][0]['files'][1] = 'test_filter_api.py'
        proposal['cards'][1]['files'].append('tests/test_old.py')
        with self.assertRaisesRegex(ValueError, 'frozen'):
            planning.validate_execution_plan(proposal, tracked)
