import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from portable_worker_recovery import RecoveryEscalation, reconcile


ISSUE = 'issue-1'
AGENT = 'agent-1'


def failed(run_id='run-1', reason='agent_error.process_failure'):
    return {'id': run_id, 'issue_id': ISSUE, 'agent_id': AGENT,
            'created_at': '2026-09-29T00:00:00Z',
            'completed_at': '2026-09-29T00:01:00Z',
            'status': 'failed', 'failure_reason': reason}


class WorkerRecoveryTests(unittest.TestCase):
    def test_one_durable_rerun_and_no_duplicate_after_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'recovery.json'
            dispatch = Mock(return_value={'id': 'run-2', 'issue_id': ISSUE, 'agent_id': AGENT})
            state = reconcile(ISSUE, AGENT, [failed()], 'todo', path,
                              dispatch, now=1790640200)
            self.assertEqual(state, 'recovery_queued')
            self.assertEqual(dispatch.call_count, 1)
            self.assertEqual(json.loads(path.read_text())['source_run_id'], 'run-1')
            self.assertEqual(reconcile(ISSUE, AGENT, [failed()], 'todo', path,
                                       dispatch, now=1790640220), 'recovery_intent_pending')
            self.assertEqual(dispatch.call_count, 1)

    def test_crash_after_intent_never_redispatches(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'recovery.json'
            path.write_text(json.dumps({'issue_id': ISSUE, 'agent_id': AGENT,
                'source_run_id': 'run-1', 'intent_at': 1790640200}))
            dispatch = Mock()
            self.assertEqual(reconcile(ISSUE, AGENT, [failed()], 'todo', path,
                                       dispatch, now=1790640220), 'recovery_intent_pending')
            with self.assertRaisesRegex(RecoveryEscalation, 'dispatch_uncertain'):
                reconcile(ISSUE, AGENT, [failed()], 'todo', path,
                          dispatch, now=1790640400)
            dispatch.assert_not_called()

    def test_second_failed_run_escalates(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'recovery.json'
            path.write_text(json.dumps({'issue_id': ISSUE, 'agent_id': AGENT,
                'source_run_id': 'run-1', 'recovery_run_id': 'run-2',
                'intent_at': 1790640200}))
            next_run = {**failed('run-2'), 'created_at': '2026-09-29T00:03:00Z'}
            with self.assertRaisesRegex(RecoveryEscalation, 'attempt_exhausted'):
                reconcile(ISSUE, AGENT, [failed(), next_run], 'todo', path,
                          Mock(), now=1790640400)

    def test_semantic_failure_and_blocked_issue_never_rerun(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'recovery.json'
            dispatch = Mock()
            with self.assertRaisesRegex(RecoveryEscalation, 'nonrecoverable'):
                reconcile(ISSUE, AGENT, [failed(reason='agent_error.iteration_limit')],
                          'todo', path, dispatch, now=1790640200)
            with self.assertRaisesRegex(RecoveryEscalation, 'issue_not_active'):
                reconcile(ISSUE, AGENT, [failed()], 'blocked', path,
                          dispatch, now=1790640200)
            dispatch.assert_not_called()
            self.assertFalse(path.exists())

    def test_active_run_waits_for_native_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'recovery.json'
            active = {**failed('run-2'), 'status': 'running',
                      'created_at': '2026-09-29T00:03:00Z'}
            dispatch = Mock()
            self.assertEqual(reconcile(ISSUE, AGENT, [failed(), active],
                                       'in_progress', path, dispatch,
                                       now=1790640200), 'worker_active')
            dispatch.assert_not_called()


if __name__ == '__main__':
    unittest.main()
