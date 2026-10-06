import json
from pathlib import Path
import tempfile
import unittest

from sequence_supervisor import supervise


class SequenceSupervisorTests(unittest.TestCase):
    def test_crash_after_predecessor_resumes_without_rerunning_it(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'sequence.json'
            path.write_text(json.dumps({'stage': 'stage_complete',
                                        'completed': ['DEP-1'], 'active': None}))
            calls = []
            def run():
                calls.append(1)
                ledger = json.loads(path.read_text())
                self.assertEqual(ledger['completed'], ['DEP-1'])
                if len(calls) == 1:
                    return 86
                ledger.update(stage='done', completed=['DEP-1', 'DEP-2'])
                path.write_text(json.dumps(ledger))
                return 0
            self.assertEqual(supervise(path, run), 0)
            self.assertEqual(len(calls), 2)
            self.assertEqual(json.loads(path.read_text())['controller_crashes'], 1)

    def test_repeated_exit_blocks_with_owner_and_next_action(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'sequence.json'
            path.write_text(json.dumps({'stage': 'working', 'completed': []}))
            calls = []
            def run():
                calls.append(1)
                return 86
            self.assertEqual(supervise(path, run), 1)
            self.assertEqual(len(calls), 2)
            ledger = json.loads(path.read_text())
            self.assertEqual(ledger['stage'], 'blocked')
            self.assertEqual(ledger['owner'], 'techlead')
            self.assertIn('diagnose', ledger['next_action'].lower())
            self.assertEqual(supervise(path, run), 1)
            self.assertEqual(len(calls), 2)

    def test_existing_blocked_incident_is_not_retried(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'sequence.json'
            path.write_text(json.dumps({'stage': 'blocked', 'category': 'failure'}))
            self.assertEqual(supervise(path, lambda: self.fail('unexpected dispatch')), 1)

    def test_opt_in_reconciliation_does_not_repeat_unresolved_incident(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'sequence.json'
            path.write_text(json.dumps({'stage': 'blocked', 'category': 'failure'}))
            calls = []
            def run():
                calls.append(1)
                return 1
            self.assertEqual(supervise(path, run, reconcile_blocked=True), 1)
            self.assertEqual(calls, [1])


if __name__ == '__main__':
    unittest.main()
