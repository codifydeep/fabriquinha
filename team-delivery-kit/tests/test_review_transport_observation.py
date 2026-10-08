import copy
import unittest
from broker.review_transport_recovery import prepare
from broker.acp_transport import failure_receipt


class ObservationTests(unittest.TestCase):
    def setUp(self):
        self.red = {'task_id': 'author', 'volume': 'frozen', 'red': {'manifest_sha256': 'a'*64}}
        self.task = {'id': 'review', 'status': 'failed', 'agent_id': 'reviewer', 'wakeup_id': 'wake',
                     'error': 'hermes session/prompt: Internal error (code=-32603)'}
        self.state = {'status': 'blocked', 'source_task': 'author', 'candidate_volume': 'frozen',
                      'manifest_sha256': 'a'*64, 'terminal_contract': 'typed-review-v1', 'wakeup_id': 'wake',
                      'review_failure': {'task_id': 'review', 'detail': 'independent test review did not complete'}}
        self.reads = {'/evidence/candidate/test.py': {'lines': 5, 'total_lines': 5}}

    def run_prepare(self, **overrides):
        return prepare(overrides.get('state', self.state), self.red, overrides.get('task', self.task),
                       'reviewer', list(self.reads), overrides.get('reads', self.reads))

    def test_same_snapshot_unknown_cause_no_verdict_and_one_attempt(self):
        before = copy.deepcopy(self.state)
        result = self.run_prepare()
        self.assertEqual(self.state, before)
        self.assertEqual(result['candidate_volume'], 'frozen')
        proof = result['transport_observation_recovery']
        self.assertEqual(proof['cause'], 'unknown')
        self.assertEqual(proof['attempt_limit'], 1)
        self.assertFalse(proof['approval']); self.assertFalse(proof['author_restarted'])
        self.assertNotIn('decision', result); self.assertNotIn('wakeup_id', result)
        with self.assertRaises(ValueError): self.run_prepare(state=result)

    def test_reject_verdict_identity_drift_partial_reads_and_other_errors(self):
        for field, value in [('decision', {'action': 'approve'}), ('candidate_volume', 'other'),
                             ('manifest_sha256', 'b'*64), ('wakeup_id', 'other')]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.run_prepare(state={**self.state, field: value})
        for field, value in [('status', 'completed'), ('agent_id', 'author'), ('error', 'budget exhausted')]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.run_prepare(task={**self.task, field: value})
        with self.assertRaises(ValueError):
            self.run_prepare(reads={next(iter(self.reads)): {'lines': 4, 'total_lines': 5}})

    def test_failure_receipt_never_reflects_raw_error_or_stderr(self):
        receipt = failure_receipt({'method': 'session/prompt', 'params': {'secret': 'PRIVATE'}},
                                  {'code': -32603, 'message': 'PRIVATE', 'data': 'PRIVATE'}, b'PRIVATE')
        self.assertNotIn('PRIVATE', str(receipt))
        self.assertEqual(receipt['cause'], 'unknown'); self.assertFalse(receipt['approval'])
        self.assertEqual(receipt['code'], -32603)
