import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from broker import failed_test_checkpoint as checkpoint
from test_test_first_handoffs import Broker

ISSUE = '11111111-1111-4111-8111-111111111111'
TASK = '22222222-2222-4222-8222-222222222222'


class FailedTestCheckpointTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.b = Broker(root / 'state.sqlite'); self.b.STATE = root
        self.b.LOCK = threading.RLock(); self.b.OWNER = 'owner'
        (root / 'native.json').write_text('{}')
        self.route = dict(issue_id=ISSUE, enabled=True, test_first=True,
                          author='author', techlead='reviewer', test_first_files=['tests/test_new.py'])
        self.task = dict(id=TASK, issue_id=ISSUE, status='failed', agent_id='author', created_at='1')
        self.runs = [self.task]
        self.red = dict(task_id=TASK, issue_id=ISSUE, red=dict(manifest_sha256='a'*64))
        self.snapshots = 0; self.captures = 0
        self.b.snapshot_submission = self.snapshot
        self.b.capture_test_first_red = self.red_capture
        self.b.docker = lambda *args: dict(Labels={'delivery-kit.owner': 'owner', 'delivery-kit.source-task': TASK})
        with self.b.db() as con:
            checkpoint.initialize(con)
            con.execute('CREATE TABLE delivery_handoffs(source_task TEXT PRIMARY KEY,issue_id TEXT,stage TEXT,owner TEXT,data TEXT,updated REAL)')
            con.execute('CREATE TABLE delivery_routes(issue_id TEXT,config TEXT)')
            con.execute('INSERT INTO delivery_routes VALUES (?,?)', (ISSUE, json.dumps(self.route)))
            con.execute('CREATE TABLE native_bindings(task_id TEXT,issue_id TEXT,request_id TEXT,agent_id TEXT,scope TEXT)')
            con.execute('INSERT INTO native_bindings VALUES (?,?,?,?,?)', (TASK, ISSUE, 'request', 'author', 'scope'))
            con.execute('CREATE TABLE grants(request_id TEXT,mode TEXT,attempt INT)')
            con.execute('INSERT INTO grants VALUES (?,?,?)', ('request', 'implementation', 1))
            con.execute('CREATE TABLE leases(request_id TEXT,status TEXT)')
            con.execute('INSERT INTO leases VALUES (?,?)', ('request', 'closed'))
            con.execute('CREATE TABLE failed_execution_snapshots(task_id TEXT,volume TEXT,status TEXT)')
            con.execute('CREATE TABLE test_first_red(issue_id TEXT,task_id TEXT,receipt TEXT)')

    def snapshot(self, payload, *, diagnostic):
        self.assertTrue(diagnostic); self.snapshots += 1
        with self.b.db() as con:
            if not con.execute('SELECT 1 FROM failed_execution_snapshots').fetchone():
                con.execute('INSERT INTO failed_execution_snapshots VALUES (?,?,?)', (TASK, 'frozen', 'complete'))
        return dict(task_id=TASK, volume='frozen', status='complete')

    def red_capture(self, payload, *, _failed_checkpoint):
        self.captures += 1
        with self.b.db() as con:
            row = con.execute('SELECT * FROM native_bindings WHERE task_id=?', (TASK,)).fetchone()
            checkpoint.validate_capture(self.b, con, row, _failed_checkpoint, self.route)
            con.execute('INSERT OR IGNORE INTO test_first_red VALUES (?,?,?)', (ISSUE, TASK, json.dumps(self.red)))
        return self.red

    def call(self):
        with patch('broker.native.issue_task_runs', return_value=self.runs), \
                patch('broker.native.task_record', return_value=self.task):
            return checkpoint.capture(self.b, ISSUE, TASK)

    def test_real_red_checkpoint_does_not_change_native_status_or_approve_delivery(self):
        result = self.call()
        self.assertEqual(result['status'], 'red_captured')
        self.assertFalse(result['native_task_completed'])
        self.assertFalse(result['delivery_approved'])
        self.assertEqual(self.task['status'], 'failed')
        with self.b.db() as con:
            self.assertTrue(checkpoint.qualified(con, ISSUE, TASK, self.red))
            self.assertFalse(checkpoint.qualified(con, ISSUE, TASK, {**self.red, 'red': {}}))
        self.assertEqual(self.call(), result)
        self.assertEqual((self.snapshots, self.captures), (1, 1))

    def test_invalid_artifact_is_not_retried(self):
        self.b.capture_test_first_red = lambda *a, **k: (_ for _ in ()).throw(ValueError('private error'))
        r = self.call(); self.assertEqual(r['status'], 'rejected')
        self.assertNotIn('private error', json.dumps(r))
        self.assertEqual(self.call(), r); self.assertEqual(self.snapshots, 1)
        with self.b.db() as con:
            self.assertFalse(checkpoint.qualified(con, ISSUE, TASK, self.red))

    def test_snapshot_failure_is_durable_and_not_repeated(self):
        self.b.snapshot_submission = lambda *a, **k: (_ for _ in ()).throw(ValueError('snapshot failure'))
        self.assertEqual(self.call()['status'], 'rejected')
        self.b.snapshot_submission = lambda *a, **k: self.fail('must not repeat')
        self.assertEqual(self.call()['status'], 'rejected')

    def test_restart_after_red_commit_finishes_same_checkpoint(self):
        self.call()
        with self.b.db() as con:
            saved = checkpoint.proof(con, ISSUE, TASK)
            saved.update(status='capturing'); saved.pop('red_receipt_sha256')
            con.execute('UPDATE failed_test_checkpoints SET receipt=?', (json.dumps(saved),))
        self.b.capture_test_first_red = lambda *a, **k: self.red
        self.assertEqual(self.call()['status'], 'red_captured')
        with self.b.db() as con:
            self.assertEqual(con.execute('SELECT count(*) FROM test_first_red').fetchone()[0], 1)

    def test_active_worker_or_native_task_prevents_capture(self):
        with self.b.db() as con: con.execute("UPDATE leases SET status='starting'")
        self.assertIsNone(self.call())
        with self.b.db() as con: con.execute("UPDATE leases SET status='closed'")
        self.runs.append(dict(id='review', agent_id='reviewer', status='running'))
        self.assertIsNone(self.call()); self.assertEqual(self.snapshots, 0)

    def test_superseded_author_or_self_review_is_not_eligible(self):
        self.assertFalse(checkpoint.eligible({**self.route, 'techlead': 'author'}, self.task, self.runs))
        later = {**self.task, 'id': 'later', 'created_at': '2'}
        self.runs.append(later)
        self.assertIsNone(self.call())

    def test_forged_keyword_without_durable_intent_is_rejected(self):
        with self.b.db() as con:
            row = con.execute('SELECT * FROM native_bindings').fetchone()
            with self.assertRaisesRegex(ValueError, 'durable'):
                checkpoint.validate_capture(self.b, con, row, dict(source_task=TASK), self.route)

    def test_snapshot_ownership_and_route_hash_are_revalidated(self):
        r = self.call(); r.update(status='capturing')
        with self.b.db() as con:
            con.execute('UPDATE failed_test_checkpoints SET receipt=?', (json.dumps(r),))
            row = con.execute('SELECT * FROM native_bindings').fetchone()
            with self.assertRaisesRegex(ValueError, 'durable'):
                checkpoint.validate_capture(self.b, con, row, r, {**self.route, 'author': 'other'})
            self.b.docker = lambda *a: dict(Labels={'delivery-kit.owner': 'foreign'})
            with self.assertRaisesRegex(ValueError, 'ownership'):
                checkpoint.validate_capture(self.b, con, row, r, self.route)

    def test_completion_flag_cannot_qualify_checkpoint(self):
        self.call()
        with self.b.db() as con:
            saved = checkpoint.proof(con, ISSUE, TASK); saved['native_task_completed'] = True
            con.execute('UPDATE failed_test_checkpoints SET receipt=?', (json.dumps(saved),))
            self.assertFalse(checkpoint.qualified(con, ISSUE, TASK, self.red))
