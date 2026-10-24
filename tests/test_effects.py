import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from fabriquinha.effects import Journal, Pending, EffectBlocked


class EffectRecovery(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.clock = [100.0]
        self.journal = Journal(Path(self.temp.name), clock=lambda: self.clock[0])

    def test_lost_ack_observes_original_effect_without_repeating(self):
        sent = []
        def send():
            sent.append('original')
            raise TimeoutError()
        with self.assertRaises(Pending):
            self.journal.do('create', {'revision': 1}, send, lambda: None)
        self.assertEqual(self.journal.do('create', {'revision': 1}, send,
                                        lambda: {'handle': 'original'}), {'handle': 'original'})
        self.assertEqual(sent, ['original'])

    def test_observation_deadline_does_not_reset_on_restart(self):
        sent = []
        def send():
            sent.append(True)
            raise TimeoutError()
        with self.assertRaises(Pending):
            self.journal.do('job', {}, send, lambda: None, timeout=10)
        self.clock[0] = 111
        restarted = Journal(Path(self.temp.name), clock=lambda: self.clock[0])
        with self.assertRaises(EffectBlocked):
            restarted.do('job', {}, send, lambda: None, timeout=10)
        self.assertEqual(len(sent), 1)

    def test_same_key_cannot_be_reused_for_another_revision(self):
        self.journal.do('deploy', {'sha': 'one'}, lambda: {'image': 'one'}, lambda: None)
        with self.assertRaises(ValueError):
            self.journal.do('deploy', {'sha': 'two'}, lambda: {'image': 'two'}, lambda: None)


if __name__ == '__main__':
    unittest.main()
