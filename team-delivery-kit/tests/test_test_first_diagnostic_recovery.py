import json
import hashlib
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch

from broker import handoffs, test_first_handoffs
from test_test_first_handoffs import Broker


class DiagnosticRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.broker = Broker(Path(self.temp.name) / 'state.sqlite')
        self.broker.STATE = Path(self.temp.name)
        self.broker.LOCK = threading.RLock()
        (self.broker.STATE / 'native.json').write_text('{}')
        self.issue = '11111111-1111-4111-8111-111111111111'
        self.source = '22222222-2222-4222-8222-222222222222'
        self.cto = '33333333-3333-4333-8333-333333333333'
        self.payload = {'issue_id': self.issue, 'source_task': self.source, 'cto_task': self.cto}
        self.route = {'test_first': True, 'enabled': True, 'author': 'author', 'cto': 'cto'}
        self.data = {'phase': 'test_first', 'error': 'test_first_cto_requires_replanning',
                     'cto_task': self.cto, 'test_first_cto_wakeup': 'wake',
                     'decision': {'action': 'escalate_cto', 'reason': 'Evidence missing'}}
        self.runs = [{'id': self.source, 'agent_id': 'author', 'status': 'completed', 'created_at': '01'},
                     {'id': self.cto, 'agent_id': 'cto', 'status': 'completed', 'wakeup_id': 'wake'}]
        self.calls = 0
        with self.broker.db() as con:
            handoffs.initialize(con)
            con.execute('INSERT INTO delivery_routes(issue_id,config) VALUES (?,?)', (self.issue, json.dumps(self.route)))
            con.execute('CREATE TABLE test_first_red(issue_id TEXT)')
            con.execute('CREATE TABLE leases(status TEXT)')
        self.save()
        def capture(payload):
            self.calls += 1
            self.assertEqual(payload, {'task_id': self.source})
            directory = self.broker.STATE / 'test-first-incidents'
            directory.mkdir(exist_ok=True)
            (directory / (self.source + '.json')).write_text(json.dumps({
                'kind': 'rejected_red', 'issue_id': self.issue, 'task_id': self.source,
                'exit_code': 0, 'manifest_sha256': 'a' * 64, 'output_excerpt': 'Ran 176 tests\nOK'}))
            raise ValueError('Red must be an executed failing test suite')
        self.broker.capture_test_first_red = capture

    def save(self):
        with self.broker.db() as con:
            handoffs.save(con, self.source, self.issue, 'test_first_blocked', 'cto', self.data, 1)

    def resume(self):
        with patch('broker.native.issue_task_runs', return_value=self.runs):
            return test_first_handoffs.resume_diagnosis(self.broker, self.payload)

    def test_replays_diagnosis_once_without_red_or_implementation_grant(self):
        self.assertTrue(self.resume()['resumed'])
        self.assertTrue(self.resume()['resumed'])
        self.assertEqual(self.calls, 1)
        with self.broker.db() as con:
            row = handoffs.load(con, self.source)
            data = json.loads(row['data'])
            self.assertEqual(row['stage'], 'technical_decision_required')
            self.assertEqual(data['diagnostic_retry'], 1)
            self.assertEqual(data['previous_cto_diagnosis']['cto_task'], self.cto)
            self.assertNotIn('test_first_cto_wakeup', data)
            self.assertIsNone(con.execute('SELECT 1 FROM test_first_red').fetchone())

    def test_rejects_prior_diagnosis_that_had_evidence(self):
        self.data['diagnostic'] = {'exit_code': 0}
        self.save()
        with self.assertRaisesRegex(ValueError, 'evidence-missing'):
            self.resume()
        self.assertEqual(self.calls, 0)

    def test_empty_test_diagnostic_replays_once_without_fabricated_red_manifest(self):
        def capture(payload):
            self.calls += 1
            directory = self.broker.STATE / 'test-first-incidents'
            directory.mkdir(exist_ok=True)
            (directory / (self.source + '.json')).write_text(json.dumps({
                'kind': 'rejected_snapshot', 'category': 'empty_new_test',
                'issue_id': self.issue, 'task_id': self.source,
                'files': {'tests/test_new.py': {'bytes': 0,
                    'sha256': hashlib.sha256(b'').hexdigest()}}}))
            raise ValueError('test-first NEW test is empty')
        self.broker.capture_test_first_red = capture
        result = self.resume()
        self.assertIsNone(result['manifest_sha256'])
        self.assertEqual(len(result['diagnostic_sha256']), 64)
        self.assertEqual(self.resume(), result)
        self.assertEqual(self.calls, 1)

    def test_unknown_snapshot_rejection_cannot_trigger_replay(self):
        def capture(payload):
            directory = self.broker.STATE / 'test-first-incidents'
            directory.mkdir(exist_ok=True)
            (directory / (self.source + '.json')).write_text(json.dumps({
                'kind': 'rejected_snapshot', 'category': 'unknown',
                'issue_id': self.issue, 'task_id': self.source}))
            raise ValueError('unknown')
        self.broker.capture_test_first_red = capture
        with self.assertRaisesRegex(ValueError, 'proven empty-test'):
            self.resume()

    def test_rejects_busy_workers_and_stale_author(self):
        with self.broker.db() as con:
            con.execute("INSERT INTO leases VALUES ('running')")
        with self.assertRaisesRegex(ValueError, 'idle workers'):
            self.resume()
        with self.broker.db() as con:
            con.execute('DELETE FROM leases')
        self.runs.append({'id': 'new', 'agent_id': 'author', 'status': 'completed', 'created_at': '02'})
        with self.assertRaisesRegex(ValueError, 'exact idle source'):
            self.resume()
        self.assertEqual(self.calls, 0)

    def test_rejects_wrong_identity_and_existing_red(self):
        with self.assertRaises(ValueError):
            test_first_handoffs.resume_diagnosis(self.broker, {**self.payload, 'command': 'anything'})
        with self.broker.db() as con:
            con.execute('INSERT INTO test_first_red VALUES (?)', (self.issue,))
        with self.assertRaisesRegex(ValueError, 'Red already exists'):
            self.resume()
        self.assertEqual(self.calls, 0)


if __name__ == '__main__':
    unittest.main()
