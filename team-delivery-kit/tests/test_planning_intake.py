import json
import unittest

from planning_intake import parse_proposal, safe_path


class PlanningIntakeTests(unittest.TestCase):
    def test_product_plan_is_structured_and_requires_acceptance(self):
        proposal = {'role': 'product', 'stories': [
            {'title': 'Add suggestion', 'acceptance': ['Title is required']}],
            'business_questions': []}
        self.assertEqual(parse_proposal(json.dumps(proposal), 'product'), proposal)
        proposal['stories'][0]['acceptance'] = []
        with self.assertRaisesRegex(ValueError, 'story'):
            parse_proposal(json.dumps(proposal), 'product')

    def test_richer_product_json_is_projected_to_verified_stories(self):
        answer = {'role': 'product', 'title': 'Feedback board',
                  'user_stories': [{'id': 'US-1', 'story': 'Create a suggestion',
                                    'acceptance_criteria': ['It appears in both browsers']}],
                  'business_questions': []}
        self.assertEqual(parse_proposal(json.dumps(answer), 'product'),
                         {'role': 'product', 'stories': [
                             {'title': 'Create a suggestion',
                              'acceptance': ['It appears in both browsers']}],
                          'business_questions': []})

    def test_technical_plan_rejects_unknown_dependency_and_runner(self):
        proposal = {'role': 'techlead', 'cards': [
            {'id': 'C1', 'title': 'API', 'owner': 'backend_data',
             'depends_on': [], 'acceptance': ['API test passes'],
             'files': ['feedback_board/server.js'], 'test_command': ['node', '--test']},
            {'id': 'C2', 'title': 'Web', 'owner': 'frontend',
             'depends_on': ['C1'], 'acceptance': ['Browser test passes'],
             'files': ['feedback_board/index.html'], 'test_command': ['node', '--test']}],
            'integration_order': ['C1', 'C2']}
        self.assertEqual(parse_proposal(json.dumps(proposal), 'techlead'), proposal)
        proposal['cards'][1]['depends_on'] = ['C3']
        with self.assertRaisesRegex(ValueError, 'dependency'):
            parse_proposal(json.dumps(proposal), 'techlead')
        proposal['cards'][1]['depends_on'] = ['C1']
        proposal['cards'][0]['test_command'] = ['sh', '-c', 'anything']
        with self.assertRaisesRegex(ValueError, 'runner'):
            parse_proposal(json.dumps(proposal), 'techlead')

    def test_repository_root_files_are_safe_but_traversal_is_not(self):
        self.assertTrue(safe_path('Dockerfile'))
        self.assertTrue(safe_path('app/server.js'))
        self.assertTrue(safe_path('.dockerignore'))
        for path in ('../secret', '/etc/passwd', '.env', 'app/../secret',
                     'app\\secret', 'app//secret', ''):
            self.assertFalse(safe_path(path))

    def test_python_runner_matches_controller_qualified_argv(self):
        proposal = {'role': 'techlead', 'cards': [
            {'id': 'C1', 'title': 'API', 'owner': 'backend_data',
             'depends_on': [], 'acceptance': ['Full suite passes'],
             'files': ['app/server.py', 'tests/test_api.py'],
             'test_command': ['python3', '-m', 'unittest', 'discover', '-s', '.', '-q']}],
            'integration_order': ['C1']}
        self.assertEqual(parse_proposal(json.dumps(proposal), 'techlead'), proposal)
        proposal['cards'][0]['test_command'] = ['python3', '-m', 'unittest', 'discover']
        with self.assertRaisesRegex(ValueError, 'runner'):
            parse_proposal(json.dumps(proposal), 'techlead')

    def test_fragmented_techlead_reply_can_be_reassembled_without_rewriting(self):
        proposal = {'role': 'techlead', 'cards': [
            {'id': 'C1', 'title': 'API', 'owner': 'backend_data',
             'depends_on': [], 'acceptance': ['API test passes'],
             'files': ['app/server.js'], 'test_command': ['node', '--test']}],
            'integration_order': ['C1']}
        text = json.dumps(proposal)
        self.assertEqual(parse_proposal(text[:43] + text[43:], 'techlead'), proposal)


if __name__ == '__main__':
    unittest.main()
