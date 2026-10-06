import json
import unittest

from dependent_replan import REQUIRED, parse


ORIGINAL = {'id': 'C2', 'title': 'Served board UI', 'owner': 'frontend',
            'depends_on': ['C1'], 'files': sorted(REQUIRED - {'app/server.py'}),
            'acceptance': ['Original product acceptance'],
            'test_command': ['python3', '-m', 'unittest', 'discover', '-s', '.', '-q']}


class DependentReplanTests(unittest.TestCase):
    def test_preserves_original_scope_and_adds_server_route(self):
        answer = {'role': 'techlead', 'decision': 'serve_static_from_existing_server',
                  'files': sorted(REQUIRED), 'rationale': 'The existing server owns same-origin routes.'}
        card = parse('```json\n' + json.dumps(answer) + '\n```', ORIGINAL)
        self.assertEqual(set(card['required_files']), REQUIRED)
        self.assertEqual(card['acceptance'][0], ORIGINAL['acceptance'][0])
        self.assertTrue(any('GET /' in item for item in card['acceptance']))

    def test_cannot_omit_server_or_add_unrelated_files(self):
        answer = {'role': 'techlead', 'decision': 'serve_static_from_existing_server',
                  'files': sorted(REQUIRED - {'app/server.py'}), 'rationale': 'No server edit.'}
        with self.assertRaises(ValueError):
            parse(json.dumps(answer), ORIGINAL)
        answer['files'] = sorted(REQUIRED | {'tests/test_feedback_api.py'})
        with self.assertRaises(ValueError):
            parse(json.dumps(answer), ORIGINAL, {'tests/test_feedback_api.py'})


if __name__ == '__main__':
    unittest.main()
