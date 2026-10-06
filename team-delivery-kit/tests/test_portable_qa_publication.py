import unittest

from portable_qa_publication import publish


class Board:
    def __init__(self):
        self.cards = {
            'parent': {'id': 'parent', 'status': 'blocked', 'metadata': {
                'execution_gate': 'blocked_deployed_qa',
                'qa_incident_issue_id': 'diagnosis'}},
            'diagnosis': {'id': 'diagnosis', 'status': 'todo',
                          'parent_issue_id': 'parent', 'metadata': {}},
            'retry': {'id': 'retry', 'status': 'todo',
                      'parent_issue_id': 'diagnosis', 'metadata': {}},
            'cto': {'id': 'cto', 'status': 'todo',
                    'parent_issue_id': 'diagnosis', 'metadata': {}},
            'repair': {'id': 'repair', 'status': 'done', 'metadata': {}}}
        self.status_writes = []

    def __call__(self, command, *args):
        if command == 'get':
            return self.cards[args[0]]
        if command == 'metadata' and args[0] == 'list':
            return self.cards[args[1]]['metadata']
        if command == 'metadata' and args[0] == 'set':
            self.cards[args[1]]['metadata'][args[args.index('--key') + 1]] = args[args.index('--value') + 1]
            return None
        if command == 'status':
            assert '--no-start' in args
            self.cards[args[0]]['status'] = args[1]
            self.status_writes.append((args[0], args[1]))
            return self.cards[args[0]]
        if command == 'runs':
            return []
        raise AssertionError((command, args))


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.board = Board()
        self.incident = {'phase': 'deployed', 'source_sha': 'a' * 40,
                         'parent_issue_id': 'parent', 'child_issue_id': 'diagnosis'}
        self.retry = {'parent_issue_id': 'diagnosis', 'child_issue_id': 'retry'}
        self.child = {'stage': 'deployed_qa_passed', 'base_sha': 'a' * 40,
                      'merge_sha': 'b' * 40, 'label': 'QA1-1', 'issue_id': 'repair',
                      'pr_url': 'https://example.test/pull/1',
                      'deployment': {'url': 'http://127.0.0.1:1'}}
        self.recovery = {'stage': 'qa_recovered_by_child', 'merge_sha': 'b' * 40,
                         'label': 'QA1-1', 'pr_url': self.child['pr_url'],
                         'qa_url': self.child['deployment']['url']}

    def test_closes_diagnosis_and_cancels_failed_parent_idempotently(self):
        first = publish(self.board, self.incident, self.retry, self.child,
                        recovery=self.recovery)
        self.assertEqual(first['parent_status'], 'cancelled')
        self.assertEqual(self.board.status_writes,
                         [('diagnosis', 'done'), ('retry', 'done'),
                          ('parent', 'cancelled')])
        self.assertEqual(self.board.cards['parent']['metadata']['qa_repair_merge_sha'], 'b' * 40)
        publish(self.board, self.incident, self.retry, self.child,
                recovery=self.recovery)
        self.assertEqual(len(self.board.status_writes), 3)

    def test_rejects_unverified_child_without_board_writes(self):
        bad = {**self.child, 'merge_sha': 'c' * 40}
        with self.assertRaisesRegex(ValueError, 'exact child'):
            publish(self.board, self.incident, self.retry, bad,
                    recovery=self.recovery)
        self.assertEqual(self.board.status_writes, [])

    def test_browser_incident_cannot_close_with_only_http_evidence(self):
        with self.assertRaisesRegex(ValueError, 'browser'):
            publish(self.board, {**self.incident, 'phase': 'browser'}, self.retry,
                    self.child, recovery=self.recovery)
        self.assertEqual(self.board.status_writes, [])

    def test_closes_cto_card_when_cto_supplied_valid_repair(self):
        cto = {'parent_issue_id': 'diagnosis', 'child_issue_id': 'cto'}
        publish(self.board, self.incident, self.retry, self.child,
                recovery=self.recovery, cto=cto)
        self.assertEqual(self.board.cards['cto']['status'], 'done')
        self.assertEqual(self.board.cards['parent']['status'], 'cancelled')

    def test_unrun_techlead_is_cancelled_not_falsely_completed(self):
        self.board.cards['diagnosis']['status'] = 'blocked'
        incident = {**self.incident, 'dispatch': 'budget_paused'}
        cto = {'parent_issue_id': 'diagnosis', 'child_issue_id': 'cto'}
        result = publish(self.board, incident, None, self.child,
                         recovery=self.recovery, cto=cto)
        self.assertEqual(result['diagnosis_status'], 'cancelled')
        self.assertEqual(self.board.cards['diagnosis']['status'], 'cancelled')
        self.assertEqual(self.board.cards['cto']['status'], 'done')
        prior_writes = list(self.board.status_writes)
        repeated = publish(self.board, incident, None, self.child,
                           recovery=self.recovery, cto=cto)
        self.assertEqual(repeated, result)
        self.assertEqual(self.board.status_writes, prior_writes)

    def test_cancelled_diagnosis_requires_direct_cto_without_runs(self):
        self.board.cards['diagnosis']['status'] = 'cancelled'
        incident = {**self.incident, 'dispatch': 'budget_paused'}
        with self.assertRaisesRegex(ValueError, 'hierarchy or state drift'):
            publish(self.board, incident, None, self.child,
                    recovery=self.recovery)
        self.assertEqual(self.board.status_writes, [])


if __name__ == '__main__':
    unittest.main()
