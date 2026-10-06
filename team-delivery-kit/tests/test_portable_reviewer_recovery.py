import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from portable_reviewer_recovery import reconcile
from portable_worker_recovery import RecoveryEscalation


ISSUE, AUTHOR, REVIEWER = 'issue-1', 'author-1', 'reviewer-1'


def runs(review_id='review-1', status='failed'):
    return [
        {'id': 'author-run', 'issue_id': ISSUE, 'agent_id': AUTHOR,
         'status': 'completed', 'created_at': '2026-09-29T00:00:00Z'},
        {'id': review_id, 'issue_id': ISSUE, 'agent_id': REVIEWER,
         'status': status, 'failure_reason': 'agent_error.process_failure',
         'created_at': '2026-09-29T00:01:00Z'},
    ]


def wakeup():
    return {'id': 'wakeup-1', 'issue_id': ISSUE, 'agent_id': REVIEWER,
            'filter_task_id': 'review-1', 'event_types': ['task.failed'],
            'kind': 'event', 'instruction': 'PORTABLE_REVIEW_RECOVERY review-1. original'}


class ReviewerRecoveryTests(unittest.TestCase):
    def test_single_targeted_wakeup_and_restart_reconciliation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'ledger.json'
            create = Mock(return_value=wakeup())
            list_wakeups = Mock(side_effect=[[], [wakeup()]])
            self.assertEqual(reconcile(ISSUE, AUTHOR, REVIEWER, runs(), 'todo',
                                       path, list_wakeups, create, now=1000),
                             'recovery_queued')
            self.assertEqual(create.call_args.args[:3], (ISSUE, REVIEWER, 'review-1'))
            self.assertEqual(reconcile(ISSUE, AUTHOR, REVIEWER, runs(), 'todo',
                                       path, list_wakeups, create, now=1020),
                             'recovery_intent_pending')
            self.assertEqual(create.call_count, 1)
            with self.assertRaisesRegex(RecoveryEscalation, 'not_started'):
                reconcile(ISSUE, AUTHOR, REVIEWER, runs(), 'todo', path,
                          lambda _: [wakeup()], create, now=1121)

    def test_crash_after_intent_never_redispatches(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'ledger.json'
            path.write_text(json.dumps({'issue_id': ISSUE, 'reviewer_id': REVIEWER,
                'source_run_id': 'author-run', 'failed_run_id': 'review-1',
                'intent_at': 1000}))
            create = Mock()
            self.assertEqual(reconcile(ISSUE, AUTHOR, REVIEWER, runs(), 'todo',
                                       path, lambda _: [], create, now=1020),
                             'recovery_intent_pending')
            with self.assertRaisesRegex(RecoveryEscalation, 'dispatch_uncertain'):
                reconcile(ISSUE, AUTHOR, REVIEWER, runs(), 'todo', path,
                          lambda _: [], create, now=1121)
            create.assert_not_called()

    def test_second_failed_review_and_semantic_failure_escalate(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'ledger.json'
            path.write_text(json.dumps({'issue_id': ISSUE, 'reviewer_id': REVIEWER,
                'source_run_id': 'author-run', 'failed_run_id': 'review-1',
                'intent_at': 1000, 'wakeup_id': 'wakeup-1'}))
            retry = runs('review-2')
            retry.insert(1, runs()[1])
            retry[-1]['created_at'] = '2026-09-29T00:02:00Z'
            with self.assertRaisesRegex(RecoveryEscalation, 'attempt_exhausted'):
                reconcile(ISSUE, AUTHOR, REVIEWER, retry, 'todo', path,
                          Mock(), Mock(), now=1020)
            path.unlink()
            semantic = runs()
            semantic[-1]['failure_reason'] = 'agent_error.iteration_limit'
            with self.assertRaisesRegex(RecoveryEscalation, 'nonrecoverable'):
                reconcile(ISSUE, AUTHOR, REVIEWER, semantic, 'todo', path,
                          Mock(), Mock(), now=1020)

    def test_provider_error_requires_broker_worker_loss_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'ledger.json'
            provider = runs()
            provider[-1]['failure_reason'] = 'agent_error.provider_server_error'
            with self.assertRaisesRegex(RecoveryEscalation, 'nonrecoverable'):
                reconcile(ISSUE, AUTHOR, REVIEWER, provider, 'todo', path,
                          Mock(), Mock(), now=1000)
            self.assertFalse(path.exists())
            self.assertEqual(reconcile(ISSUE, AUTHOR, REVIEWER, provider, 'todo',
                                       path, lambda _: [], Mock(return_value=wakeup()),
                                       now=1000, worker_loss_verified=True),
                             'recovery_queued')


if __name__ == '__main__':
    unittest.main()
