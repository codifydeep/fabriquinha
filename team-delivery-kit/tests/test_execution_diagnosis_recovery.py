import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from unittest.mock import Mock

from broker import execution_diagnosis_recovery as recovery, handoffs
from test_test_first_handoffs import Broker


class ExecutionDiagnosisRecoveryTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.b = Broker(Path(tmp.name) / 'state.sqlite')
        self.b.STATE = Path(tmp.name); self.b.LOCK = threading.RLock()
        (self.b.STATE / 'native.json').write_text('{}')
        self.issue = '11111111-1111-4111-8111-111111111111'
        self.source = '22222222-2222-4222-8222-222222222222'
        self.failed = '33333333-3333-4333-8333-333333333333'
        self.payload = dict(issue_id=self.issue, source_task=self.source, failed_task=self.failed)
        self.route = dict(enabled=True, author='author', cto='cto')
        self.data = dict(source_status='failed', source_failure_reason='agent_error.process_failure',
            error='recipient_execution_failed', recipient_task=self.failed, target='cto',
            failed_dispatch_stage='diagnose_cto', wakeup_id='wake', instruction='Generic diagnosis',
            phase_evidence=dict(red=dict(exit_code=1, manifest='immutable')))
        self.runs = [dict(id=self.source, agent_id='author', status='failed',
            failure_reason='agent_error.process_failure', created_at='01'),
            dict(id=self.failed, agent_id='cto', status='failed', wakeup_id='wake',
            error='hermes provider error: API call failed after 1 retries', created_at='02')]
        with self.b.db() as c:
            handoffs.initialize(c)
            c.execute('CREATE TABLE leases(request_id TEXT,status TEXT)')
            c.execute('INSERT INTO delivery_routes VALUES (?,?)', (self.issue, json.dumps(self.route)))
            handoffs.save(c, self.source, self.issue, 'technical_decision_required', 'cto', self.data, 1)

    def register(self):
        with patch.object(recovery.native, 'issue_task_runs', return_value=self.runs):
            return recovery.register(self.b, self.payload)

    def test_once_replays_diagnosis_not_author_and_keeps_original_red(self):
        result = self.register(); self.assertEqual(self.register(), result)
        self.assertFalse(result['author_retry_authorized']); self.assertFalse(result['delivery_approval'])
        with self.b.db() as c:
            row = handoffs.load(c, self.source)
            self.assertEqual(c.execute('SELECT count(*) FROM execution_diagnosis_repairs').fetchone()[0], 1)
        data = json.loads(row['data'])
        self.assertEqual(row['stage'], 'diagnose_cto'); self.assertEqual(row['owner'], 'cto')
        self.assertEqual(data['phase_evidence'], self.data['phase_evidence'])
        self.assertEqual(json.loads(result['previous_handoff']['data']), self.data)
        self.assertNotIn('recipient_task', data)

    def test_active_lease_and_newer_author_are_rejected(self):
        with self.b.db() as c: c.execute('INSERT INTO leases VALUES (?,?)', ('active', 'running'))
        with self.assertRaises(ValueError): self.register()
        with self.b.db() as c: c.execute('DELETE FROM leases')
        self.runs.append(dict(id='new', agent_id='author', status='failed', created_at='03'))
        with self.assertRaises(ValueError): self.register()

    def test_functional_failure_or_already_typed_instruction_cannot_replay(self):
        for mutation in (dict(validation_failure=dict(category='executed_test_failure')),
                         dict(instruction='DELIVERY_EXECUTION_DIAGNOSIS_V1'),
                         dict(source_failure_reason='agent_error.iteration_limit')):
            with self.subTest(mutation=mutation):
                with self.b.db() as c:
                    handoffs.save(c, self.source, self.issue, 'technical_decision_required',
                                  'cto', {**self.data, **mutation}, 1)
                with self.assertRaises(ValueError): self.register()

    def test_pin_drift_and_other_native_failure_are_rejected(self):
        # Simulate actual source drift, independent of which historical pin is
        # currently installed. Every explicitly qualified revision stays pinned.
        with patch.object(recovery.Path, 'read_bytes', return_value=b'unapproved controller source'):
            with self.assertRaises(ValueError): self.register()
        self.runs[1]['error'] = 'functional error'
        with self.assertRaises(ValueError): self.register()

    def test_changed_replay_identity_cannot_consume_second_attempt(self):
        self.register()
        self.payload['failed_task'] = '44444444-4444-4444-8444-444444444444'
        with self.assertRaises(ValueError): self.register()

    def format_fixture(self):
        self.register()
        self.failed = '44444444-4444-4444-8444-444444444444'
        self.payload['failed_task'] = self.failed
        self.runs[1]['id'] = self.failed
        with self.b.db() as c:
            d = json.loads(handoffs.load(c, self.source)['data'])
            d.update(error='recipient_execution_failed', recipient_task=self.failed,
                     target='cto', failed_dispatch_stage='diagnose_cto', wakeup_id='wake',
                     instruction='DELIVERY_EXECUTION_DIAGNOSIS_V1\nDELIVERY_TYPED_DECISION_V1')
            handoffs.save(c, self.source, self.issue, 'technical_decision_required', 'cto', d, 2)
            c.execute('CREATE TABLE native_bindings(request_id TEXT,task_id TEXT,agent_id TEXT,issue_id TEXT)')
            c.execute('INSERT INTO native_bindings VALUES (?,?,?,?)', ('execution', self.failed, 'cto', self.issue))
        self.proof = dict(operation='rejected_typed_decision_adapter_v1', category='typed_schema_maxLength',
                          upstream_sha256='a'*64, delivery_approval=False, worker_tool_executed=False)

    def format_register(self):
        with patch.object(recovery.native, 'issue_task_runs', return_value=self.runs), \
             patch.object(recovery, 'format_rejection', return_value=self.proof):
            return recovery.register_format(self.b, self.payload)

    def test_format_replay_is_separate_once_only_and_preserves_evidence(self):
        self.format_fixture()
        result = self.format_register()
        self.assertEqual(result, self.format_register())
        self.assertFalse(result['author_retry_authorized'])
        with self.b.db() as c:
            d = json.loads(handoffs.load(c, self.source)['data'])
            self.assertEqual(c.execute('SELECT count(*) FROM execution_diagnosis_repairs').fetchone()[0], 1)
        self.assertIn('execution_diagnosis_contract_repair', d)
        self.assertEqual(d['phase_evidence'], self.data['phase_evidence'])
        self.assertEqual(d['execution_diagnosis_format_repair']['execution_id'], 'execution')

    def test_format_replay_rejects_unrelated_rejection_and_binding(self):
        self.format_fixture()
        self.proof['category'] = 'nonterminal_or_non_json_response'
        with self.assertRaises(ValueError): self.format_register()
        self.proof['category'] = 'typed_schema_maxLength'
        with self.b.db() as c: c.execute("UPDATE native_bindings SET agent_id='author'")
        with self.assertRaises(ValueError): self.format_register()

    def test_format_replay_rejects_active_execution_and_second_identity(self):
        self.format_fixture()
        with self.b.db() as c: c.execute("INSERT INTO leases VALUES ('active','running')")
        with self.assertRaises(ValueError): self.format_register()
        with self.b.db() as c: c.execute('DELETE FROM leases')
        self.format_register()
        self.payload['failed_task'] = '55555555-5555-4555-8555-555555555555'
        with self.assertRaises(ValueError): self.format_register()

    def test_receipt_reader_requires_pinned_owned_running_proxy(self):
        b = Mock(); b.PREFIX = 'delivery-kit-port2'
        proxy = dict(Image=recovery.FORMAT_PROXY_IMAGE, Id='owned', State=dict(Running=True),
                     Config=dict(Labels={'com.docker.compose.project': b.PREFIX,
                                         'com.docker.compose.service': 'model-proxy'}))
        for mutation in (dict(Image='other'), dict(State=dict(Running=False)), dict(Config=dict(Labels={}))):
            b.docker.return_value = {**proxy, **mutation}
            with self.assertRaises(ValueError): recovery.format_rejection(b, self.source)
        self.assertFalse(b.DockerConnection.called)

    def test_receipt_reader_uses_readonly_database_and_exact_execution(self):
        b = Mock(); b.PREFIX = 'delivery-kit-port2'
        proxy = dict(Image=recovery.FORMAT_PROXY_IMAGE, Id='owned', State=dict(Running=True),
                     Config=dict(Labels={'com.docker.compose.project': b.PREFIX,
                                         'com.docker.compose.service': 'model-proxy'}))
        b.docker.side_effect = [proxy, dict(Id='exec'), dict(Running=False, ExitCode=0)]
        response = b.DockerConnection.return_value.getresponse.return_value
        response.status = 200; response.read.return_value = b'[{"category":"typed_schema_maxLength"}]'
        self.assertEqual(recovery.format_rejection(b, self.source)['category'], 'typed_schema_maxLength')
        args = b.docker.call_args_list[1].args[2]['Cmd']
        self.assertEqual(args[-1], self.source)
        self.assertIn('?mode=ro', args[2])
        b.DockerConnection.return_value.close.assert_called_once()
