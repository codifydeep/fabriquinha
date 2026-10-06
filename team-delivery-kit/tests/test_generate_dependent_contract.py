import unittest

from dependent_replan import REQUIRED
from generate_dependent_contract import derive


class GeneratedDependentContractTests(unittest.TestCase):
    def test_c2_preserves_baseline_tests_and_qa_checks_static_content(self):
        card = {'id': 'C2', 'title': 'Served board UI', 'owner': 'frontend',
                'depends_on': ['C1'], 'files': sorted(REQUIRED),
                'required_files': sorted(REQUIRED), 'acceptance': ['Red', 'Green'],
                'test_command': ['python3', '-m', 'unittest', 'discover', '-s', '.', '-q']}
        tracked = ['Dockerfile.feedback-bootstrap', 'app/server.py',
                   'tests/test_feedback_api.py', 'tests/test_bootstrap_health.py']
        runtime = {'test_image': 'python@sha256:' + 'a' * 64}
        contract, spec = derive(card, tracked, runtime)
        self.assertEqual(contract['schema_version'], 2)
        self.assertIn('app/server.py', contract['editable_files'])
        self.assertIn('tests/test_feedback_api.py', contract['protected_files'])
        self.assertIn('tests/test_bootstrap_health.py', contract['required_files'])
        self.assertEqual([case['path'] for case in contract['qa_cases']],
                         ['/health', '/', '/static/app.js', '/static/style.css'])
        self.assertEqual(spec['implementer_registry'], 'pilot-frontend.json')


if __name__ == '__main__':
    unittest.main()
