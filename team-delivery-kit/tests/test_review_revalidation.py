from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from broker import handoffs, review_revalidation as repair


class ReviewRevalidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'state.sqlite'
        (Path(self.temp.name) / 'native.json').write_text('{}')
        self.issue = '01a0f80a-30c2-744a-a3ae-5120c875dbbc'
        self.source = '01a0f80d-38bd-7e7f-9b03-698f983a961c'
        self.review = '01a0f80e-2323-7ca2-a07b-60b2a0b60e8e'
        self.payload = {'issue_id': self.issue, 'source_task': self.source,
                        'review_task': self.review, 'manifest_sha256': 'a' * 64,
                        'worker_image': 'sha256:' + 'b' * 64}
        self.broker = SimpleNamespace(db=self.db, LOCK=threading.RLock(),
            STATE=Path(self.temp.name), IMAGE=self.payload['worker_image'],
            validate_frozen_delivery=lambda *_: {'manifest_sha256': 'a' * 64,
                                                'baseline_tests_intact': True})
        self.data = {'recipient_task': self.review, 'target': 'reviewer',
                     'evidence': {'manifest_sha256': 'a' * 64},
                     'snapshot': {'volume': 'frozen'}, 'wakeup_id': 'old-wakeup'}
        with self.db() as con:
            handoffs.initialize(con)
            con.execute('INSERT INTO delivery_routes VALUES (?,?)',
                        (self.issue, json.dumps({'enabled': False, 'reviewer': 'reviewer'})))
            con.execute('CREATE TABLE leases(status TEXT)')
            con.execute('CREATE TABLE native_bindings(request_id TEXT,task_id TEXT,agent_id TEXT,issue_id TEXT)')
            con.execute('CREATE TABLE review_bindings(request_id TEXT,volume TEXT)')
            con.execute('INSERT INTO native_bindings VALUES (?,?,?,?)',
                        ('request', self.review, 'reviewer', self.issue))
            con.execute("INSERT INTO review_bindings VALUES ('request','frozen')")
            con.execute('CREATE TABLE reviews(review_task_id TEXT PRIMARY KEY,source_task_id TEXT, '
                        'reviewer_agent_id TEXT,manifest_sha256 TEXT,status TEXT)')
            con.execute('INSERT INTO reviews VALUES (?,?,?,?,?)',
                        (self.review, self.source, 'reviewer', 'a' * 64, 'approved'))
            handoffs.save(con, self.source, self.issue, 'approved', 'reviewer', self.data, 1)
        self.messages = [{'type': 'tool_result', 'tool': 'python',
                          'output': 'Exit code: 0\nRED reproduction (guard removed)'}]
        for patcher in (patch.object(repair.native, 'task_record', return_value={'status': 'completed'}),
                        patch.object(repair.native, 'task_messages', side_effect=lambda *_: self.messages)):
            patcher.start()
            self.addCleanup(patcher.stop)

    @contextmanager
    def db(self):
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        try:
            with con:
                yield con
        finally:
            con.close()

    def test_preserves_original_and_reopens_only_review_idempotently(self):
        result = repair.reopen(self.broker, self.payload)
        self.assertEqual(repair.reopen(self.broker, self.payload), result)
        with self.db() as con:
            self.assertEqual(con.execute('SELECT status FROM reviews').fetchone()[0], 'policy_invalidated')
            row = handoffs.load(con, self.source)
            self.assertEqual(row['stage'], 'ready_review')
            data = json.loads(row['data'])
            self.assertNotIn('recipient_task', data)
            self.assertEqual(data['review_retries'], 1)
            original = json.loads(con.execute('SELECT original FROM review_policy_revalidations').fetchone()[0])
            self.assertEqual(original['review']['status'], 'approved')
            self.assertEqual(json.loads(original['handoff']['data']), self.data)

    def test_active_worker_or_enabled_route_cannot_reopen(self):
        with self.db() as con:
            con.execute("INSERT INTO leases VALUES ('running')")
        with self.assertRaisesRegex(ValueError, 'paused idle'):
            repair.reopen(self.broker, self.payload)

    def test_old_unrecorded_review_is_fenced_against_late_approval(self):
        with self.db() as con:
            con.execute('DELETE FROM reviews')
        repair.reopen(self.broker, self.payload)
        with self.db() as con:
            self.assertEqual(con.execute('SELECT status FROM reviews').fetchone()[0], 'policy_invalidated')

    def test_missing_actual_violation_and_changed_snapshot_are_rejected(self):
        self.messages = []
        with self.assertRaisesRegex(ValueError, 'recorded forbidden'):
            repair.reopen(self.broker, self.payload)
        self.messages = [{'type': 'tool_result', 'tool': 'python',
                          'output': 'Exit code: 0\nRED reproduction'}]
        self.broker.validate_frozen_delivery = lambda *_: {'manifest_sha256': 'c' * 64}
        with self.assertRaisesRegex(ValueError, 'preserved delivery'):
            repair.reopen(self.broker, self.payload)
        with self.db() as con:
            self.assertEqual(con.execute('SELECT status FROM reviews').fetchone()[0], 'approved')

    def test_worker_image_and_prior_review_identity_are_exact(self):
        with self.assertRaisesRegex(ValueError, 'image drift'):
            repair.reopen(self.broker, {**self.payload, 'worker_image': 'old'})
        with self.assertRaisesRegex(ValueError, 'exact prior'):
            repair.reopen(self.broker, {**self.payload, 'review_task': self.source})
