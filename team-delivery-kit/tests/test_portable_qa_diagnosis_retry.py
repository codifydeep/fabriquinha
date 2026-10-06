import tempfile
import unittest

from portable_qa_diagnosis_retry import find, record


PARENT = '11111111-1111-4111-8111-111111111111'
CHILD = '22222222-2222-4222-8222-222222222222'
RETRY = '33333333-3333-4333-8333-333333333333'
TECHLEAD = '44444444-4444-4444-8444-444444444444'
SHA = 'a' * 40
INCIDENT = {'key': 'd34db33f12345678', 'phase': 'deployed', 'label': 'QATEST-1',
            'source_sha': SHA, 'parent_issue_id': PARENT, 'child_issue_id': CHILD,
            'techlead_id': TECHLEAD,
            'category': 'post-deploy content type mismatch: /static/app.js'}
CONTRACT = {'editable_files': ['app/server.py', 'tests/test_placeholder.py'],
            'test_files': ['tests/test_old.py', 'tests/test_placeholder.py'],
            'test_roots': ['.'],
            'qa_cases': [{'path': '/static/app.js', 'status': 200,
                          'content_type': 'application/javascript',
                          'text_contains': ['/feedback']}]}


class FakeCLI:
    def __init__(self):
        self.cards = {CHILD: {'id': CHILD, 'status': 'todo', 'metadata': {}}}
        self.runs = []
        self.created = 0
        self.started = 0

    def __call__(self, command, *args):
        if command == 'search':
            return {'issues': [self.cards[RETRY]] if RETRY in self.cards else []}
        if command == 'create':
            self.created += 1
            card = {'id': RETRY, 'title': args[args.index('--title') + 1],
                    'parent_issue_id': CHILD, 'status': 'blocked',
                    'assignee_id': None, 'metadata': {}}
            self.cards[RETRY] = card
            return card
        if command == 'get':
            return self.cards[args[0]]
        if command == 'metadata' and args[0] == 'list':
            return self.cards[args[1]]['metadata']
        if command == 'metadata' and args[0] == 'set':
            card = self.cards[args[1]]
            card['metadata'][args[args.index('--key') + 1]] = args[args.index('--value') + 1]
            return card['metadata']
        if command == 'assign':
            self.cards[args[0]]['assignee_id'] = args[args.index('--to-id') + 1]
            return self.cards[args[0]]
        if command == 'status':
            self.cards[args[0]]['status'] = args[1]
            return self.cards[args[0]]
        if command == 'runs':
            return self.runs
        if command == 'rerun':
            self.started += 1
            self.runs.append({'agent_id': TECHLEAD, 'status': 'running',
                              'id': 'task-2'})
            return self.runs[-1]
        raise AssertionError((command, args))


class DiagnosisRetryTests(unittest.TestCase):
    def kwargs(self):
        return {'incident': INCIDENT, 'parent_contract': CONTRACT,
                'task_id': 'task-1', 'reason': 'QA repair new test path is unsafe'}

    def test_budget_pause_resume_and_deduplicate(self):
        with tempfile.TemporaryDirectory() as directory:
            cli = FakeCLI()
            first = record(directory, cli, **self.kwargs(), budget_ready=False)
            self.assertEqual(first['dispatch'], 'budget_paused')
            self.assertEqual(cli.started, 0)
            second = record(directory, cli, **self.kwargs(), budget_ready=True)
            self.assertEqual(second['dispatch'], 'techlead_started')
            self.assertEqual(cli.started, 1)
            record(directory, cli, **self.kwargs(), budget_ready=True)
            self.assertEqual(cli.created, 1)
            self.assertEqual(cli.started, 1)
            self.assertEqual(find(directory, INCIDENT['key'])['child_issue_id'], RETRY)

    def test_rejected_task_or_reason_cannot_change(self):
        with tempfile.TemporaryDirectory() as directory:
            cli = FakeCLI()
            record(directory, cli, **self.kwargs(), budget_ready=False)
            with self.assertRaisesRegex(ValueError, 'identity drift'):
                record(directory, cli, **{**self.kwargs(), 'task_id': 'other'},
                       budget_ready=False)


if __name__ == '__main__':
    unittest.main()
