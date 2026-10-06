import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from coordination_store import CoordinationStore


class CoordinationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'coordination.db'
        self.store = CoordinationStore(self.path)
        self.addCleanup(self.store.close)
        self.store.create_attempt('attempt-2', 'board-2', 'v0.1')

    def test_single_active_attempt(self):
        with self.assertRaises(ValueError):
            self.store.create_attempt('attempt-3', 'board-3', 'v0.1')

    def test_stale_attempt_rejected(self):
        with self.assertRaises(ValueError):
            self.store.handoff('old-attempt', 'h1', 't1', 'backend_data', 'techlead', ['commit:abc'], 'review', 100)

    def test_handoff_requires_artifact_and_expected_result(self):
        with self.assertRaises(ValueError):
            self.store.handoff('attempt-2', 'h1', 't1', 'backend_data', 'techlead', [], 'review', 100)

    def test_accept_only_recipient_and_once(self):
        self.store.handoff('attempt-2', 'h1', 't1', 'backend_data', 'techlead', ['commit:abc'], 'review', 100)
        with self.assertRaises(ValueError):
            self.store.accept('attempt-2', 'h1', 'cto', 'run1')
        self.assertTrue(self.store.accept('attempt-2', 'h1', 'techlead', 'run1'))
        self.assertFalse(self.store.accept('attempt-2', 'h1', 'techlead', 'run1'))
        with self.assertRaises(ValueError):
            self.store.accept('attempt-2', 'h1', 'techlead', 'old-run')

    def test_incident_recurrence_has_new_identity(self):
        one = self.store.incident('attempt-2', 't1', 'blocked:1', 'cto', 'dependency')
        self.assertEqual(one, self.store.incident('attempt-2', 't1', 'blocked:1', 'cto', 'dependency'))
        two = self.store.incident('attempt-2', 't1', 'blocked:2', 'cto', 'dependency')
        self.assertNotEqual(one, two)

    def test_repeated_action_budget_is_evidence_bound(self):
        incident = self.store.incident('attempt-2', 't1', 'blocked:1', 'cto', 'dependency')
        for key in ('a1', 'a2'):
            self.assertTrue(self.store.reserve_action('attempt-2', incident, key, 'retry', 'evidence1'))
        self.assertFalse(self.store.reserve_action('attempt-2', incident, 'a1', 'retry', 'evidence1'))
        with self.assertRaises(ValueError):
            self.store.reserve_action('attempt-2', incident, 'a3', 'retry', 'evidence1')
        self.assertTrue(self.store.reserve_action('attempt-2', incident, 'a4', 'retry', 'evidence2'))

    def test_outbox_survives_restart_and_deduplicates(self):
        self.store.enqueue('attempt-2', 'event1', 'started')
        self.store.enqueue('attempt-2', 'event1', 'started')
        other = CoordinationStore(self.path)
        self.addCleanup(other.close)
        self.assertEqual(len(other.pending('attempt-2')), 1)
        other.sent('attempt-2', 'event1')
        self.assertEqual(self.store.pending('attempt-2'), [])

    def test_no_homologation_from_discovery(self):
        with self.assertRaises(ValueError):
            self.store.transition('attempt-2', 'EM_DESCOBERTA', 'HOMOLOGADA', 'techlead', {'receipt': 'fake'})

    def test_cancel_requires_ceo(self):
        with self.assertRaises(ValueError):
            self.store.transition('attempt-2', 'EM_DESCOBERTA', 'CANCELADA_PELO_CEO', 'cto', {'reason': 'timeout'})
        self.store.transition('attempt-2', 'EM_DESCOBERTA', 'CANCELADA_PELO_CEO', 'ceo', {'reason': 'restart'})
        self.store.create_attempt('attempt-3', 'board-3', 'v0.1')

    def test_decision_does_not_accept_wrong_actor_or_old_attempt(self):
        self.store.question('attempt-2', 'q1', 't1', 'produto', 'business', 'Choose scope?', ['a', 'b'], 'user123', 100)
        with self.assertRaises(ValueError):
            self.store.answer('attempt-2', 'q1', 'intruder', 'a', 50)
        with self.assertRaises(ValueError):
            self.store.answer('old', 'q1', 'user123', 'a', 50)
        self.assertTrue(self.store.answer('attempt-2', 'q1', 'user123', 'a', 50))
        self.assertFalse(self.store.answer('attempt-2', 'q1', 'user123', 'a', 50))
        with self.assertRaises(ValueError):
            self.store.answer('attempt-2', 'q1', 'user123', 'b', 50)

    def test_expired_decision_rejected(self):
        self.store.question('attempt-2', 'q1', 't1', 'produto', 'business', 'Choose?', ['a', 'b'], 'user123', 100)
        with self.assertRaises(ValueError):
            self.store.answer('attempt-2', 'q1', 'user123', 'a', 101)

    def test_technical_question_cannot_be_escalated_to_ceo(self):
        with self.assertRaises(ValueError):
            self.store.question('attempt-2', 'q1', 't1', 'cto', 'architecture', 'Choose stack?', ['a', 'b'], 'user123', 100)


if __name__ == '__main__':
    unittest.main()
