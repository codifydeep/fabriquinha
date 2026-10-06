from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from broker import handoffs
from broker.suite_failure import evidence, FrozenSuiteFailure
from broker.suite_diagnosis_repair import reopen, challenge


class SuiteDiagnosisRepairTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'state.sqlite'
        self.source = '01a0f52f-e252-77b9-a22f-1c12c61a550f'
        self.failure = evidence(1, 'FAIL: test_new (tests.test_new.New.test_new)\n'
                                'AssertionError: private\nRan 114 tests\nFAILED (failures=1)',
                                self.source, 'frozen')
        self.broker = SimpleNamespace(LOCK=threading.RLock(), db=self.db,
                                     validate_frozen_delivery=Mock(side_effect=FrozenSuiteFailure(self.failure)))
        self.payload = {'source_task': self.source, 'failure_signature': 'a' * 64}
        with self.db() as con:
            handoffs.initialize(con)
            con.execute('CREATE TABLE snapshots(task_id TEXT,volume TEXT,status TEXT)')
            con.execute('CREATE TABLE leases(status TEXT)')
            con.execute('INSERT INTO snapshots VALUES (?,?,?)', (self.source, 'frozen', 'complete'))
            con.execute('INSERT INTO delivery_routes VALUES (?,?)', ('issue', json.dumps(
                {'enabled': True, 'techlead': 'lead'})))
            handoffs.save(con, self.source, 'issue', 'technical_decision_required', 'cto',
                          {'error': 'portable frozen suite failed', 'failure_signature': 'a' * 64,
                           'wakeup_id': 'old', 'dispatch_marker': 'old', 'control_error_count': 2}, 100)

    @contextmanager
    def db(self):
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        try:
            with con:
                yield con
        finally:
            con.close()

    def test_restart_is_idempotent_preserving_historic_event(self):
        first = reopen(self.broker, self.payload)
        self.assertEqual(reopen(self.broker, self.payload), first)
        self.broker.validate_frozen_delivery.assert_called_once_with('frozen', self.source)
        with self.db() as con:
            state = handoffs.load(con, self.source)
            self.assertEqual(state['stage'], 'diagnose')
            data = json.loads(state['data'])
            self.assertEqual(data['validation_failure'], self.failure)
            self.assertNotIn('wakeup_id', data)
            self.assertEqual(con.execute('SELECT count(*) FROM delivery_handoff_events').fetchone()[0], 2)

    def test_active_worker_prevents_mutation_or_suite_execution(self):
        with self.db() as con:
            con.execute("INSERT INTO leases VALUES ('running')")
        with self.assertRaisesRegex(ValueError, 'idle'):
            reopen(self.broker, self.payload)
        self.broker.validate_frozen_delivery.assert_not_called()

    def test_identity_drift_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'recorded'):
            reopen(self.broker, {**self.payload, 'failure_signature': 'b' * 64})

    def test_artifact_cto_requires_pause_and_verified_idle_native_source(self):
        self.broker.STATE = Path(self.temp.name)
        (self.broker.STATE / 'native.json').write_text('{}')
        payload = {**self.payload, 'mode': 'artifact_cto'}
        with self.assertRaisesRegex(ValueError, 'paused route'):
            reopen(self.broker, payload)
        with self.db() as con:
            con.execute('UPDATE delivery_routes SET config=?', (json.dumps(
                {'enabled': False, 'techlead': 'lead', 'cto': 'cto', 'author': 'author'}),))
        with patch('broker.native.issue_task_runs', return_value=[
                {'id': self.source, 'status': 'running', 'agent_id': 'author'}]):
            with self.assertRaisesRegex(ValueError, 'idle tasks'):
                reopen(self.broker, payload)
        self.broker.validate_frozen_delivery.assert_not_called()
        with patch('broker.native.issue_task_runs', return_value=[
                {'id': self.source, 'status': 'completed', 'agent_id': 'author'}]):
            receipt = reopen(self.broker, payload)
            self.assertEqual(reopen(self.broker, payload), receipt)
        with self.db() as con:
            state = handoffs.load(con, self.source)
            self.assertEqual(state['stage'], 'diagnose_cto')
            self.assertTrue(json.loads(state['data'])['artifact_diagnosis'])
            data = json.loads(state['data'])
            data.update(control_error='ValueError:handoff instruction too large', control_error_count=2)
            handoffs.save(con, self.source, 'issue', 'technical_decision_required', 'cto', data, 200)
        repaired = reopen(self.broker, payload)
        self.assertTrue(repaired['transport_repaired'])
        self.assertEqual(reopen(self.broker, payload), repaired)
        with self.db() as con:
            self.assertEqual(handoffs.load(con, self.source)['stage'], 'diagnose_cto')
        self.broker.validate_frozen_delivery.assert_called_once()
        with self.db() as con:
            state = handoffs.load(con, self.source)
            data = json.loads(state['data'])
            data.update(failed_dispatch_stage='diagnose_cto', recipient_task='failed-recipient',
                recipient_error='hermes session/prompt failed: session/prompt: restricted broker stream failed: broker_internal (code=-32000)')
            handoffs.save(con, self.source, 'issue', 'technical_decision_required', 'cto', data, 300)
        with patch('broker.native.issue_task_runs', return_value=[
                {'id': 'failed-recipient', 'status': 'failed'}]):
            context_receipt = reopen(self.broker, payload)
            self.assertTrue(context_receipt['context_repaired'])
            self.assertEqual(reopen(self.broker, payload), context_receipt)
        with self.db() as con:
            self.assertEqual(handoffs.load(con, self.source)['stage'], 'diagnose_cto')

    def test_no_green_or_unknown_infrastructure_failure_can_reopen(self):
        for result in (None, ValueError('missing interpreter')):
            self.broker.validate_frozen_delivery.side_effect = result
            with self.assertRaises(ValueError):
                reopen(self.broker, self.payload)
        with self.db() as con:
            self.assertEqual(handoffs.load(con, self.source)['stage'], 'technical_decision_required')

    def challenge_setup(self):
        self.broker.STATE = Path(self.temp.name)
        (self.broker.STATE / 'native.json').write_text('{}')
        with self.db() as con:
            con.execute('UPDATE delivery_routes SET config=?', (json.dumps(
                {'enabled': False, 'cto': 'cto', 'author': 'author'}),))
            data = {'error': 'portable frozen suite failed', 'failure_signature': 'a' * 64,
                    'validation_failure': self.failure, 'recipient_task': 'cto-decision',
                    'target': 'cto', 'decision': {'action': 'request_test_revision',
                                                'reason': 'test defect', 'optional_files': []}}
            handoffs.save(con, self.source, 'issue', 'test_revision_required', 'reviewer', data, 300)
        return {**self.payload, 'decision_task': 'cto-decision',
                'output_sha256': self.failure['output_sha256'],
                'observation': 'Read product event bindings and mock URL matching; claims conflict.'}

    def test_challenge_is_once_bound_to_decision_and_not_an_approval(self):
        payload = self.challenge_setup()
        runs = [{'id': 'cto-decision', 'status': 'completed', 'agent_id': 'cto'}]
        with patch('broker.native.issue_task_runs', return_value=runs):
            receipt = challenge(self.broker, payload)
            self.assertEqual(challenge(self.broker, payload), receipt)
        with self.db() as con:
            state = handoffs.load(con, self.source)
            data = json.loads(state['data'])
            self.assertEqual(state['stage'], 'diagnose_cto')
            self.assertEqual(data['diagnostic_challenge']['observation'], payload['observation'])
            self.assertNotIn('decision', data)
            self.assertNotIn('recipient_task', data)
            self.assertEqual(data['validation_failure'], self.failure)
            data.update(recipient_task='new-decision', target='cto',
                        decision={'action': 'request_test_revision'})
            handoffs.save(con, self.source, 'issue', 'test_revision_required', 'reviewer', data, 400)
        with self.assertRaisesRegex(ValueError, 'already challenged'):
            challenge(self.broker, {**payload, 'decision_task': 'new-decision'})
        self.broker.validate_frozen_delivery.assert_not_called()

    def test_challenge_rejects_drift_active_tasks_and_unbounded_notes(self):
        payload = self.challenge_setup()
        for field, value in [('failure_signature', 'b' * 64),
                             ('output_sha256', 'c' * 64), ('decision_task', 'stale'),
                             ('observation', 'x' * 181)]:
            with self.assertRaises(ValueError):
                challenge(self.broker, {**payload, field: value})
        with patch('broker.native.issue_task_runs', return_value=[
                {'id': 'cto-decision', 'status': 'running', 'agent_id': 'cto'}]):
            with self.assertRaisesRegex(ValueError, 'idle'):
                challenge(self.broker, payload)
        with self.db() as con:
            self.assertEqual(handoffs.load(con, self.source)['stage'], 'test_revision_required')
