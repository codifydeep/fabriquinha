import tempfile
import unittest

from portable_qa_cto import find, record


class Board:
    def __init__(self):
        self.cards = {
            'diagnosis': {'id': 'diagnosis', 'status': 'todo', 'metadata': {}}}
        self.runs = []
        self.starts = 0

    def __call__(self, command, *args):
        if command == 'search':
            return {'issues': [self.cards['cto']] if 'cto' in self.cards else []}
        if command == 'create':
            self.cards['cto'] = {'id': 'cto',
                                 'title': args[args.index('--title') + 1],
                                 'parent_issue_id': 'diagnosis',
                                 'status': 'blocked', 'assignee_id': None,
                                 'metadata': {}}
            return self.cards['cto']
        if command == 'get':
            return self.cards['cto']
        if command == 'metadata' and args[0] == 'list':
            return self.cards['diagnosis' if args[1] == 'diagnosis' else 'cto']['metadata']
        if command == 'metadata' and args[0] == 'set':
            self.cards['diagnosis' if args[1] == 'diagnosis' else 'cto']['metadata'][
                args[args.index('--key') + 1]] = args[args.index('--value') + 1]
            return None
        if command == 'assign':
            self.assert_no_start(args)
            self.cards['cto']['assignee_id'] = args[args.index('--to-id') + 1]
            return self.cards['cto']
        if command == 'status':
            self.assert_no_start(args)
            self.cards['cto']['status'] = args[1]
            return self.cards['cto']
        if command == 'runs':
            return self.runs
        if command == 'rerun':
            self.starts += 1
            self.runs.append({'id': 'task-1', 'agent_id': 'cto-agent',
                              'status': 'running'})
            return self.runs[-1]
        raise AssertionError((command, args))

    @staticmethod
    def assert_no_start(args):
        if '--no-start' not in args:
            raise AssertionError('unexpected implicit agent start')


class CtoEscalationTests(unittest.TestCase):
    def setUp(self):
        self.incident = {'key': '12345678abcdefab', 'source_sha': 'a' * 40,
                         'child_issue_id': 'diagnosis',
                         'category': 'post-deploy content type mismatch: /static/app.js'}
        self.contract = {'editable_files': ['app/server.py', 'tests/test_base.py'],
                         'test_files': ['tests/test_base.py'],
                         'test_roots': ['tests'],
                         'qa_cases': [{'path': '/static/app.js'}]}

    def test_one_card_one_run_and_budget_pause(self):
        with tempfile.TemporaryDirectory() as directory:
            board = Board()
            args = dict(incident=self.incident, parent_contract=self.contract,
                        cto_id='cto-agent', reason='Tech Lead retry rejected')
            first = record(directory, board, **args, budget_ready=False)
            self.assertEqual(first['dispatch'], 'budget_paused')
            self.assertEqual(board.starts, 0)
            second = record(directory, board, **args, budget_ready=True)
            self.assertEqual(second['dispatch'], 'cto_started')
            self.assertEqual(board.starts, 1)
            record(directory, board, **args, budget_ready=True)
            self.assertEqual(board.starts, 1)
            self.assertEqual(find(directory, self.incident['key'])['child_issue_id'], 'cto')
            self.assertEqual(board.cards['cto']['metadata']['qa_source_sha'], 'a' * 40)

    def test_rejects_reason_drift_and_foreign_run(self):
        with tempfile.TemporaryDirectory() as directory:
            board = Board()
            args = dict(incident=self.incident, parent_contract=self.contract,
                        cto_id='cto-agent', reason='Tech Lead retry rejected')
            record(directory, board, **args, budget_ready=False)
            with self.assertRaisesRegex(ValueError, 'identity drift'):
                record(directory, board, **{**args, 'reason': 'different'},
                       budget_ready=False)
            board.runs.append({'id': 'foreign', 'agent_id': 'wrong',
                               'status': 'completed'})
            with self.assertRaisesRegex(ValueError, 'foreign'):
                record(directory, board, **args, budget_ready=True)


if __name__ == '__main__':
    unittest.main()
