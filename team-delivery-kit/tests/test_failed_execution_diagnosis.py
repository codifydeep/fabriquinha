from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from broker import handoffs, native, handoff_runtime
from broker.failed_execution_diagnosis import register
from broker.suite_failure import FrozenSuiteFailure, evidence


class FailedExecutionDiagnosisTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'state.sqlite'
        self.source = '01a0fd11-34f8-7748-8836-c6402f662635'
        self.payload = {'source_task': self.source, 'failure_signature': 'a' * 64}
        self.failure = evidence(1, 'FAIL: test_new (tests.test_new.New.test_new)\n'
                                'Ran 243 tests\nFAILED (failures=1)', self.source, 'diagnostic')
        self.broker = SimpleNamespace(LOCK=threading.RLock(), db=self.db,
            STATE=Path(self.temp.name), handoff_runtime=handoff_runtime,
            snapshot_submission=Mock(return_value={'volume': 'diagnostic'}),
            verify_test_first_green=Mock(),
            validate_frozen_delivery=Mock(side_effect=FrozenSuiteFailure(self.failure)))
        (self.broker.STATE / 'native.json').write_text('{}')
        self.runs = [{'id': self.source, 'agent_id': 'author', 'status': 'failed'}]
        with self.db() as con:
            handoffs.initialize(con)
            con.execute('CREATE TABLE leases(status TEXT)')
            con.execute('CREATE TABLE snapshots(task_id TEXT,volume TEXT,status TEXT)')
            con.execute('INSERT INTO delivery_routes VALUES (?,?)', ('issue', json.dumps(
                {'enabled': False, 'author': 'author', 'cto': 'cto'})))
            handoffs.save(con, self.source, 'issue', 'technical_decision_required', 'cto',
                          {'error': 'author_execution_failed', 'failure_signature': 'a' * 64,
                           'recipient_task': 'old', 'phase_evidence': {'red': 'preserved'}}, 100)

    @contextmanager
    def db(self):
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        try:
            with con:
                yield con
        finally:
            con.close()

    def run_register(self):
        with patch.object(native, 'issue_task_runs', return_value=self.runs), \
             patch.object(handoff_runtime, 'Effects', autospec=True) as effects:
            effects.return_value.test_first_red.return_value = {'red': 'immutable'}
            return register(self.broker, self.payload)

    def test_failed_snapshot_is_not_submission_and_restart_is_idempotent(self):
        receipt = self.run_register()
        self.assertEqual(receipt['status'], 'diagnostic_only_not_approved')
        self.assertEqual(receipt['failure']['phase'], 'failed_execution_diagnostic')
        self.assertEqual(self.run_register(), receipt)
        self.broker.snapshot_submission.assert_called_once_with({'task_id': self.source}, diagnostic=True)
        with self.db() as con:
            self.assertEqual(con.execute('SELECT count(*) FROM snapshots').fetchone()[0], 0)
            row = handoffs.load(con, self.source)
            self.assertEqual(row['stage'], 'diagnose_cto')
            data = json.loads(row['data'])
            self.assertEqual(data['phase_evidence'], {'red': 'preserved'})
            self.assertNotIn('recipient_task', data)

    def test_running_worker_rejected_before_snapshot(self):
        with self.db() as con:
            con.execute("INSERT INTO leases VALUES ('running')")
        with self.assertRaisesRegex(ValueError, 'paused idle'):
            self.run_register()
        self.broker.snapshot_submission.assert_not_called()

    def test_active_route_rejected(self):
        with self.db() as con:
            con.execute('UPDATE delivery_routes SET config=?', (json.dumps(
                {'enabled': True, 'author': 'author', 'cto': 'cto'}),))
        with self.assertRaisesRegex(ValueError, 'paused idle'):
            self.run_register()

    def test_completed_source_cannot_use_failed_path(self):
        self.runs[0]['status'] = 'completed'
        with self.assertRaisesRegex(ValueError, 'latest failed'):
            self.run_register()

    def test_passing_suite_does_not_approve_or_dispatch(self):
        self.broker.validate_frozen_delivery.side_effect = None
        with self.assertRaisesRegex(ValueError, 'runtime diagnosis remains blocked'):
            self.run_register()
        with self.db() as con:
            self.assertEqual(handoffs.load(con, self.source)['stage'], 'technical_decision_required')

    def test_infrastructure_failure_does_not_authorize_test_revision(self):
        self.broker.validate_frozen_delivery.side_effect = TimeoutError('deadline')
        with self.assertRaisesRegex(ValueError, 'infrastructure diagnosis remains blocked'):
            self.run_register()

    def test_caller_cannot_choose_volume_or_command(self):
        with self.assertRaisesRegex(ValueError, 'exact failed'):
            register(self.broker, {**self.payload, 'command': 'arbitrary'})

    def test_changed_handoff_rejected_after_capture(self):
        def mutate(*args):
            with self.db() as con:
                con.execute("UPDATE delivery_handoffs SET stage='cancelled'")
            raise FrozenSuiteFailure(self.failure)
        self.broker.validate_frozen_delivery.side_effect = mutate
        with self.assertRaisesRegex(ValueError, 'changed during'):
            self.run_register()
