from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch, Mock
from broker import handoffs
from broker.test_review_challenge import reopen


class ReviewChallengeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.con = sqlite3.connect(':memory:'); self.con.row_factory = sqlite3.Row
        self.addCleanup(self.con.close); handoffs.initialize(self.con)
        for sql in ('CREATE TABLE test_revision_trials(issue_id TEXT,config TEXT,state TEXT)',
                    'CREATE TABLE test_first_red(issue_id TEXT,receipt TEXT)', 'CREATE TABLE leases(status TEXT)'):
            self.con.execute(sql)
        self.issue = '11111111-1111-4111-8111-111111111111'
        self.source = '22222222-2222-4222-8222-222222222222'
        self.review = '33333333-3333-4333-8333-333333333333'
        self.cto = '44444444-4444-4444-8444-444444444444'
        self.claim = 'Cases.test_nonexistent'
        self.payload = {'issue_id': self.issue, 'source_task': self.source, 'review_task': self.review,
                        'decision_task': self.cto, 'manifest_sha256': 'a'*64, 'claimed_missing_method': self.claim}
        self.state = {'status': 'blocked', 'source_task': self.source, 'review_task': self.review,
            'manifest_sha256': 'a'*64, 'candidate_volume': 'candidate', 'previous_volume': 'previous',
            'read_evidence': {'test': 'read'}, 'wakeup_id': 'review-wake',
            'rejection_diagnosis': {'status': 'revision_required', 'decision_task': self.cto,
                'wakeup_id': 'cto-wake', 'decision': {'reason': self.claim+' was removed'}}}
        self.red = {'task_id': self.source, 'volume': 'candidate',
                    'red': {'manifest_sha256': 'a'*64, 'test_sha256': {'test_case.py': 'b'*64}}}
        old_red = {'volume': 'previous', 'red': {'manifest_sha256': 'c'*64}}
        self.con.execute('INSERT INTO test_revision_trials VALUES (?,?,?)',
                         (self.issue, json.dumps({'reviewer': 'lead', 'old_red': old_red}), json.dumps(self.state)))
        self.con.execute('INSERT INTO test_first_red VALUES (?,?)', (self.issue, json.dumps(self.red)))
        self.con.execute('INSERT INTO delivery_routes VALUES (?,?)', (self.issue, json.dumps({
            'enabled': False, 'test_first_files': ['test_case.py'], 'cto': 'cto'})))
        @contextmanager
        def db(): yield self.con
        root = Path(self.tmp.name); (root / 'native.json').write_text('{}')
        self.broker = SimpleNamespace(db=db, LOCK=threading.RLock(), STATE=root)
        self.summary = {'candidate_manifest': 'a'*64, 'previous_manifest': 'c'*64,
                        'files': {'test_case.py': {'removed_methods': [], 'previous_methods': ['Cases.test_keep']}}}
        self.compare = Mock(return_value=self.summary)
        self.runs = [{'id': self.review, 'status': 'completed', 'agent_id': 'lead', 'wakeup_id': 'review-wake'},
                     {'id': self.cto, 'status': 'completed', 'agent_id': 'cto', 'wakeup_id': 'cto-wake'}]

    def run_challenge(self, payload=None):
        with patch('broker.native.issue_task_runs', return_value=self.runs):
            return reopen(self.broker, payload or self.payload, comparison=self.compare)

    def test_challenge_preserves_rejection_red_and_requires_fresh_review_once(self):
        self.assertEqual(self.run_challenge(), self.run_challenge())
        self.compare.assert_called_once()
        receipt = json.loads(self.con.execute('SELECT receipt FROM test_review_challenges').fetchone()[0])
        self.assertEqual(receipt['prior_state'], self.state)
        state = json.loads(self.con.execute('SELECT state FROM test_revision_trials').fetchone()[0])
        self.assertEqual(state['status'], 'dispatch_intent')
        self.assertEqual(state['evidence_policy'], 1)
        self.assertNotIn('review_task', state)
        self.assertNotIn('read_evidence', state)
        self.assertEqual(json.loads(self.con.execute('SELECT receipt FROM test_first_red').fetchone()[0]), self.red)
        with self.assertRaisesRegex(ValueError, 'identity drift'):
            self.run_challenge({**self.payload, 'claimed_missing_method': 'Other.test_fake'})

    def test_real_removed_method_or_nonexistent_claim_context_cannot_reopen(self):
        self.summary['files']['test_case.py']['removed_methods'] = ['Cases.test_real']
        with self.assertRaisesRegex(ValueError, 'not contradicted'):
            self.run_challenge()
        self.summary['files']['test_case.py']['removed_methods'] = []
        with self.assertRaisesRegex(ValueError, 'exact completed'):
            self.run_challenge({**self.payload, 'claimed_missing_method': 'Other.test_fake'})

    def test_active_worker_changed_manifest_and_wrong_actor_are_rejected(self):
        self.con.execute("INSERT INTO leases VALUES ('running')")
        with self.assertRaisesRegex(ValueError, 'paused idle'):
            self.run_challenge()
        self.con.execute('DELETE FROM leases')
        with self.assertRaisesRegex(ValueError, 'exact completed'):
            self.run_challenge({**self.payload, 'manifest_sha256': 'd'*64})
        self.runs[1]['agent_id'] = 'author'
        with self.assertRaisesRegex(ValueError, 'terminal review'):
            self.run_challenge()
