import json
from pathlib import Path
from unittest.mock import patch

import unittest
import test_suite_diagnosis_repair as fixture
from broker import handoffs
from broker.execution_stall_recovery import register


class ExecutionStallRecoveryTests(unittest.TestCase):
    # Reuse the isolated database fixture, not its functional-failure tests.
    def setUp(self):
        fixture.SuiteDiagnosisRepairTests.setUp(self)
        self.broker.STATE = Path(self.temp.name)
        self.broker.IMAGE = 'sha256:' + 'd' * 64
        from unittest.mock import MagicMock
        proxy = MagicMock()
        proxy.__enter__.return_value.read.return_value = b'{"response_deadline_seconds":120,"runtime_decision_contract":"no-tools-json-v1"}'
        proxy_patch = patch('broker.execution_stall_recovery.urllib.request.urlopen', return_value=proxy)
        proxy_patch.start(); self.addCleanup(proxy_patch.stop)
        (self.broker.STATE / 'native.json').write_text('{}')
        self.request = {**self.payload, 'worker_image': self.broker.IMAGE}
        self.runs = [{'id': self.source, 'status': 'failed', 'agent_id': 'author'},
                     {'id': 'decision', 'status': 'completed', 'agent_id': 'cto'}]
        with self.db() as con:
            con.execute('UPDATE delivery_routes SET config=?', (json.dumps(
                {'enabled': False, 'cto': 'cto', 'author': 'author'}),))
            handoffs.save(con, self.source, 'issue', 'technical_decision_required', 'cto',
                {'error': 'author_execution_failed', 'source_failure_reason': 'idle_watchdog',
                 'failure_signature': 'a'*64, 'target': 'cto', 'recipient_task': 'decision',
                 'decision': {'action': 'escalate_cto'}, 'phase_evidence': {'red': 'preserved'}}, 100)

    db = fixture.SuiteDiagnosisRepairTests.db

    def test_execution_restart_is_idempotent_and_not_approval(self):
        with patch('broker.native.issue_task_runs', return_value=self.runs):
            receipt = register(self.broker, self.request)
            self.assertEqual(register(self.broker, self.request), receipt)
        self.assertEqual(receipt['status'], 'runtime_changed_not_delivery_approved')
        with self.db() as con:
            row = handoffs.load(con, self.source)
            self.assertEqual(row['stage'], 'diagnose_cto')
            self.assertEqual(json.loads(row['data'])['phase_evidence'], {'red': 'preserved'})
            self.assertEqual(con.execute('SELECT count(*) FROM execution_stall_repairs').fetchone()[0], 1)

    def test_execution_repair_rejects_identity_active_worker_and_functional_failure(self):
        with self.assertRaises(ValueError):
            register(self.broker, {**self.request, 'worker_image': 'sha256:'+'e'*64})
        with self.db() as con:
            con.execute("INSERT INTO leases VALUES ('running')")
        with self.assertRaises(ValueError):
            register(self.broker, self.request)
        with self.db() as con:
            con.execute('DELETE FROM leases')
            row = handoffs.load(con, self.source)
            data = json.loads(row['data']); data['validation_failure'] = {'category': 'executed_test_failure'}
            handoffs.save(con, self.source, 'issue', row['stage'], 'cto', data, 100)
            # An unrelated later dependency read must not erase the exact
            # recorded malformed decision, nor create a decision approval.
            data['control_error'] = 'URLError:temporary proxy DNS lookup'
            handoffs.save(con, self.source, 'issue', row['stage'], 'cto', data, 110)
        with self.assertRaises(ValueError):
            register(self.broker, self.request)

    def test_execution_repair_rejects_running_native_task(self):
        with patch('broker.native.issue_task_runs', return_value=[*self.runs,
                {'id': 'active', 'status': 'running'}]):
            with self.assertRaisesRegex(ValueError, 'idle native'):
                register(self.broker, self.request)

    def test_changed_transport_reopens_only_recorded_malformed_cto_without_approval(self):
        with self.db() as con:
            row = handoffs.load(con, self.source); data = json.loads(row['data'])
            data.pop('decision')
            data.update(control_error='JSONDecodeError:Expecting value', execution_repair_format_retry=True,
                        execution_repair={'request': {'worker_image':'sha256:'+'e'*64}})
            handoffs.save(con, self.source, 'issue', row['stage'], 'cto', data, 100)
        with patch('broker.native.issue_task_runs', return_value=self.runs):
            receipt = register(self.broker, self.request)
            self.assertEqual(register(self.broker, self.request), receipt)
        self.assertEqual(receipt['decision_transport_repair'], 'no-tools-json-v1')
        with self.db() as con:
            self.assertEqual(handoffs.load(con, self.source)['stage'], 'diagnose_cto')
