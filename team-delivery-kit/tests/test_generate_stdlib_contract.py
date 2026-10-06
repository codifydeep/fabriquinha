import unittest

from generate_stdlib_contract import PYTHON_RUNNER, derive


class GenerateStdlibContractTests(unittest.TestCase):
    def test_c1_contract_protects_all_existing_nested_tests(self):
        tracked = ['AGENTS.md', 'Dockerfile.feedback-bootstrap', 'app/server.py',
                   'test_calc.py', 'slug_tests/test_german.py',
                   'tests/__init__.py', 'tests/test_bootstrap_health.py']
        card = {'id': 'C1', 'title': 'API', 'owner': 'backend_data',
                'depends_on': [], 'acceptance': ['Red, Green, full suite'],
                'files': ['app/server.py', 'app/db.py', 'tests/test_feedback_api.py'],
                'test_command': PYTHON_RUNNER}
        contract, spec = derive(card, tracked, {'test_image': 'python@sha256:' + 'a' * 64})
        self.assertIn('slug_tests/test_german.py', contract['protected_files'])
        self.assertIn('tests/test_bootstrap_health.py', contract['test_files'])
        self.assertIn('tests/test_feedback_api.py', contract['editable_files'])
        self.assertEqual(spec['dockerfile'], 'Dockerfile.feedback-bootstrap')
        self.assertIn('Deliver every required editable file', spec['description'])
        self.assertIn('app/db.py', spec['description'])
        card['files'].append('tests/test_bootstrap_health.py')
        with self.assertRaisesRegex(ValueError, 'baseline'):
            derive(card, tracked, {'test_image': 'python@sha256:' + 'a' * 64})


if __name__ == '__main__':
    unittest.main()
