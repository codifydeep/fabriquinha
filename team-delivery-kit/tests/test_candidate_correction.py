import json
import sqlite3
import threading
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

from broker import candidate_correction, handoffs
from portable_candidate_recovery import correction_payload, verify_preserved_tests


class CandidateCorrectionTests(unittest.TestCase):
    def test_operator_adapter_accepts_only_the_fixed_new_registration_path(self):
        from prepare_issue_base import broker_post
        with patch('prepare_issue_base.subprocess.run') as run:
            broker_post('/v1/candidate-corrections', {'finding': 'fixed'})
            self.assertEqual(run.call_args.args[0][-1], '/v1/candidate-corrections')
            with self.assertRaisesRegex(ValueError, 'unsupported operator'):
                broker_post('/v1/arbitrary-command', {'command': 'unsafe'})

    def setUp(self):
        self.con = sqlite3.connect(':memory:')
        self.con.row_factory = sqlite3.Row
        self.addCleanup(self.con.close)
        handoffs.initialize(self.con)
        self.con.execute('CREATE TABLE test_first_red(issue_id TEXT)')
        self.con.execute('INSERT INTO test_first_red VALUES ("issue")')
        self.con.execute('INSERT INTO delivery_routes VALUES (?,?)',
                         ('issue', json.dumps({'author': 'author', 'enabled': False})))
        handoffs.save(self.con, 'source', 'issue', 'approved', 'reviewer',
                      {'evidence': {'manifest_sha256': 'a' * 64}}, 1)
        @contextmanager
        def db():
            with self.con:
                yield self.con
        self.broker = SimpleNamespace(LOCK=threading.RLock(), db=db)
        self.payload = {'issue_id': 'issue', 'source_task': 'source',
                        'manifest_sha256': 'a' * 64, 'incident_key': 'b' * 16,
                        'finding': 'Correct the frozen failing HTTP assertion; preserve tests.'}

    def test_invalidates_gate_and_is_idempotent_across_restart(self):
        result = candidate_correction.register(self.broker, self.payload)
        self.assertEqual(result['status'], 'registered')
        self.assertEqual(handoffs.load(self.con, 'source')['stage'], 'correct_author')
        self.assertTrue(json.loads(self.con.execute('SELECT config FROM delivery_routes').fetchone()[0])['enabled'])
        self.assertEqual(candidate_correction.register(self.broker, self.payload), result)
        self.assertEqual(self.con.execute('SELECT count(*) FROM candidate_corrections').fetchone()[0], 1)
        with self.assertRaisesRegex(ValueError, 'identity drift'):
            candidate_correction.register(self.broker, {**self.payload, 'finding': 'different'})

    def test_rejects_stale_snapshot_and_unreviewed_submission(self):
        with self.assertRaisesRegex(ValueError, 'snapshot drift'):
            candidate_correction.register(self.broker, {**self.payload, 'manifest_sha256': 'c' * 64})
        self.con.execute('UPDATE delivery_handoffs SET stage="accepted"')
        with self.assertRaisesRegex(ValueError, 'exact approved'):
            candidate_correction.register(self.broker, self.payload)

    def test_test_preservation_includes_tests_created_by_the_original_author(self):
        contract = {'test_files': ['new_test.py'], 'protected_files': ['policy']}
        before = {'new_test.py': b'assert True', 'policy': b'policy', 'app.js': b'old'}
        verify_preserved_tests(before, {**before, 'app.js': b'fixed'}, contract)
        with self.assertRaisesRegex(ValueError, 'frozen tests'):
            verify_preserved_tests(before, {**before, 'new_test.py': b'pass'}, contract)
        with self.assertRaisesRegex(ValueError, 'topology'):
            verify_preserved_tests(before, {'app.js': b'fixed'}, contract)

    def test_payload_rejects_merged_candidates_and_test_edit_proposals(self):
        context = {'issue_id': 'issue'}
        receipt = {'head_sha': 'd' * 40, 'delivery': {'source_task': 'source', 'manifest_sha256': 'a' * 64}}
        incident = {'key': 'b' * 16, 'phase': 'candidate', 'source_sha': 'd' * 40,
                    'category': 'post-deploy content mismatch: /static/app.js'}
        contract = {'editable_files': ['app.js', 'new_test.py'], 'test_files': ['new_test.py'],
                    'qa_cases': [{'path': '/static/app.js', 'status': 200, 'text_contains': ['marker']}]}
        proposal = {'decision': 'repair', 'root_cause': 'Missing container wiring.', 'editable_code_files': ['app.js']}
        payload = correction_payload(context, receipt, incident, contract, json.dumps(proposal))
        self.assertIn('Correct product behavior, not marker comments', payload['finding'])
        with self.assertRaisesRegex(ValueError, 'bounded code-only'):
            correction_payload(context, receipt, incident, contract, json.dumps({**proposal, 'editable_code_files': ['new_test.py']}))
        with self.assertRaisesRegex(ValueError, 'unmerged pre-PR'):
            correction_payload(context, {**receipt, 'merge_sha': 'e' * 40}, incident, contract, json.dumps(proposal))
