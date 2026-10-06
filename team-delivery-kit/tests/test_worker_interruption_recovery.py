import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch, Mock
from broker import worker_interruption_recovery as recovery, handoffs
from broker import worker_recovery_transport as transport
from test_test_first_handoffs import Broker


class WorkerInterruptionRecoveryTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.b = Broker(Path(tmp.name) / 'state.sqlite'); self.b.STATE = Path(tmp.name)
        self.b.LOCK = threading.RLock(); self.b.IMAGE = 'sha256:'+'a'*64
        self.b.PREFIX = 'delivery-kit-port2'; self.b.OWNER = 'owned'
        (self.b.STATE / 'native.json').write_text('{}')
        self.issue = '11111111-1111-4111-8111-111111111111'
        self.source = '22222222-2222-4222-8222-222222222222'
        self.cto = '33333333-3333-4333-8333-333333333333'
        self.request = '44444444-4444-4444-8444-444444444444'
        self.payload = dict(issue_id=self.issue, source_task=self.source, decision_task=self.cto)
        self.route = dict(enabled=True, author='author', cto='cto', contract_sha256='b'*64)
        self.phase = dict(phase='implementation', red_exit_code=1, red_manifest='c'*64,
                         frozen_test_hashes={'tests/test_new.py': 'd'*64}, independent_test_review='approved')
        self.data = dict(source_status='failed', source_failure_reason='agent_error.process_failure',
                         error='author_execution_failed', recipient_task=self.cto, target='cto', wakeup_id='wake',
                         decision=dict(action='escalate_cto', optional_files=[], reason='Probe initialization'),
                         phase_evidence=self.phase)
        self.fault = dict(issue_id=self.issue, task_id=self.source, request_id=self.request,
                          signal='SIGKILL', accepted_tools_before=0, ownership_revalidated=True,
                          container_id='e'*64, at=1)
        folder = self.b.STATE / 'fault-injection'; folder.mkdir()
        (folder / (self.source + '.json')).write_text(json.dumps(self.fault))
        self.runs = [dict(id=self.source, agent_id='author', status='failed', created_at='01',
                         failure_reason='agent_error.process_failure'),
                     dict(id=self.cto, agent_id='cto', status='completed', wakeup_id='wake', created_at='02')]
        with self.b.db() as c:
            handoffs.initialize(c)
            c.execute('CREATE TABLE leases(request_id TEXT,scenario TEXT,name TEXT,status TEXT)')
            c.execute('CREATE TABLE native_bindings(request_id TEXT,task_id TEXT,agent_id TEXT,issue_id TEXT,scope TEXT)')
            c.execute('CREATE TABLE tool_events(request_id TEXT,tool_count INTEGER)')
            c.execute('INSERT INTO leases VALUES (?,?,?,?)', (self.request, 'acp-session', 'owned-job', 'failed'))
            c.execute('INSERT INTO native_bindings VALUES (?,?,?,?,?)', (self.request, self.source, 'author', self.issue, 'scope'))
            c.execute('INSERT INTO delivery_routes VALUES (?,?)', (self.issue, json.dumps(self.route)))
            handoffs.save(c, self.source, self.issue, 'technical_decision_required', 'cto', self.data, 1)
        self.b.docker = Mock(return_value=None)
        def submit(p, **kwargs):
            self.assertEqual(kwargs, dict(trusted_acp=True))
            with self.b.db() as c:
                c.execute('INSERT INTO leases VALUES (?,?,?,?)', (p['request_id'], 'acp', 'probe', 'passed'))
            return dict(status='passed')
        self.b.submit = Mock(side_effect=submit)

    def register(self):
        with patch.object(recovery.native, 'issue_task_runs', return_value=self.runs), \
             patch.object(recovery.handoff_runtime.Effects, 'phase_evidence', return_value=self.phase), \
             patch.object(recovery.host_restart_recovery, 'preserve', return_value=dict(
                 baseline_unchanged=True, frozen_tests_unchanged=True, frozen_test_hashes=self.phase['frozen_test_hashes'],
                 manifest_sha256='f'*64, volume='snapshot', diagnostic_only=True, delivery_approval=False)):
            return recovery.register(self.b, self.payload)

    def test_once_registers_probe_and_cto_decision_not_author_retry(self):
        receipt = self.register(); self.assertEqual(self.register(), receipt)
        self.b.submit.assert_called_once()
        self.assertFalse(receipt['author_retry_authorized']); self.assertFalse(receipt['delivery_approval'])
        with self.b.db() as c:
            row = handoffs.load(c, self.source); d = json.loads(row['data'])
            self.assertTrue(recovery.qualified(c, self.issue, self.source, d))
        self.assertEqual(row['stage'], 'diagnose_cto')
        self.assertEqual(d['phase_evidence'], self.phase)
        self.assertEqual(receipt['previous_handoff']['stage'], 'technical_decision_required')

    def test_rejects_tools_new_author_and_other_signal(self):
        with self.b.db() as c: c.execute('INSERT INTO tool_events VALUES (?,?)', (self.request, 1))
        with self.assertRaises(ValueError): self.register()
        with self.b.db() as c: c.execute('DELETE FROM tool_events')
        self.runs.append(dict(id='new', agent_id='author', status='failed', created_at='03'))
        with self.assertRaises(ValueError): self.register()
        self.runs.pop(); self.fault['signal'] = 'SIGTERM'
        (self.b.STATE/'fault-injection'/(self.source+'.json')).write_text(json.dumps(self.fault))
        with self.assertRaises(ValueError): self.register()
        self.b.submit.assert_not_called()

    def test_uncertain_probe_intent_never_resubmits(self):
        self.b.submit.side_effect = TimeoutError('uncertain')
        with self.assertRaises(TimeoutError): self.register()
        self.assertEqual(self.register()['stage'], 'probe_pending')
        self.b.submit.assert_called_once()
        with self.b.db() as c:
            receipt=json.loads(c.execute('SELECT receipt FROM worker_interruption_recoveries').fetchone()[0])
            receipt['at']=0
            c.execute('UPDATE worker_interruption_recoveries SET receipt=?',(json.dumps(receipt),))
        with self.assertRaisesRegex(ValueError,'unresolved'):self.register()
        self.b.submit.assert_called_once()

    def test_forged_receipt_or_changed_identity_cannot_qualify(self):
        receipt = self.register()
        with self.b.db() as c:
            data = json.loads(handoffs.load(c, self.source)['data'])
            data['worker_interruption_recovery']['delivery_approval'] = True
            self.assertFalse(recovery.qualified(c, self.issue, self.source, data))
        self.payload['decision_task'] = self.source
        with self.assertRaises(ValueError): self.register()

    def test_local_admission_repair_does_not_repeat_uncertain_docker_dispatch(self):
        self.b.submit.side_effect=ValueError('unknown fixed scenario')
        with self.assertRaises(ValueError):self.register()
        self.b.validate=Mock(side_effect=ValueError('unknown fixed scenario'))
        self.b.submit.side_effect=None
        first=recovery.resume_rejected_probe_admission(self.b,self.payload)
        self.assertEqual(recovery.resume_rejected_probe_admission(self.b,self.payload),first)
        self.assertEqual(self.b.submit.call_count,2)  # rejected local call plus first admission
        self.assertFalse(first['probe_admission_repair']['author_retry_authorized'])
        self.assertFalse(first['probe_admission_repair']['delivery_approval'])

    def test_admission_repair_rejects_existing_lease(self):
        self.b.submit.side_effect=TimeoutError('unknown')
        with self.assertRaises(TimeoutError):self.register()
        with self.b.db() as c:
            receipt=json.loads(c.execute('SELECT receipt FROM worker_interruption_recoveries').fetchone()[0])
            c.execute('INSERT INTO leases VALUES (?,?,?,?)',(receipt['probe_request'],'acp','probe','failed'))
        with self.assertRaises(ValueError):recovery.resume_rejected_probe_admission(self.b,self.payload)
        self.b.submit.assert_called_once()

    def transport_fixture(self):
        self.register()
        self.failed='55555555-5555-4555-8555-555555555555'
        self.transport_payload=dict(issue_id=self.issue,source_task=self.source,failed_task=self.failed)
        self.runs[1].update(id=self.failed,status='failed',error='hermes provider error: API call failed after 1 retries')
        with self.b.db() as c:
            d=json.loads(handoffs.load(c,self.source)['data'])
            d.update(error='recipient_execution_failed',recipient_task=self.failed,target='cto',wakeup_id='wake',
                failed_dispatch_stage='diagnose_cto',instruction='DELIVERY_WORKER_INTERRUPTION_RECOVERY_V1')
            handoffs.save(c,self.source,self.issue,'technical_decision_required','cto',d,2)
            c.execute('INSERT INTO native_bindings VALUES (?,?,?,?,?)',('execution',self.failed,'cto',self.issue,'diagnosis'))
        self.rejection=dict(operation='fixed_runtime_schema_truncation_v1',execution_id='execution',
            author_retry_authorized=False,delivery_approval=False,event=dict(status=502,
                execution_id='execution',route='/api/v1/chat/completions',
                category='structured_decision_response_invalid',finish_reason='length',completion_tokens=8192,
                tool_count=0,decision_schema='delivery_decision_v1',strict_schema=True,
                structured_rejection_category='nonterminal_or_non_json_response'))

    def transport_register(self):
        with patch.object(transport.native,'issue_task_runs',return_value=self.runs), \
             patch.object(transport,'rejection',return_value=self.rejection), \
             patch.object(transport,'verify_proxy'):
            return transport.register(self.b,self.transport_payload)

    def test_transport_replay_is_once_only_and_does_not_authorize_retry(self):
        self.transport_fixture()
        receipt=self.transport_register();self.assertEqual(self.transport_register(),receipt)
        self.assertFalse(receipt['author_retry_authorized'])
        with self.b.db() as c:
            row=handoffs.load(c,self.source);d=json.loads(row['data'])
            self.assertTrue(recovery.qualified(c,self.issue,self.source,d))
        self.assertEqual(row['stage'],'diagnose_cto')
        self.assertEqual(d['phase_evidence'],self.phase)
        self.assertFalse(d.get('worker_interruption_recovery_used',False))

    def test_transport_replay_rejects_other_failure_binding_and_reuse(self):
        self.transport_fixture();self.rejection['event']['finish_reason']='stop'
        with self.assertRaises(ValueError):self.transport_register()
        self.rejection['event']['finish_reason']='length'
        with self.b.db() as c:c.execute("UPDATE native_bindings SET agent_id='author' WHERE task_id=?",(self.failed,))
        with self.assertRaises(ValueError):self.transport_register()
        with self.b.db() as c:c.execute("UPDATE native_bindings SET agent_id='cto' WHERE task_id=?",(self.failed,))
        self.transport_register();self.transport_payload['failed_task']=self.source
        with self.assertRaises(ValueError):self.transport_register()
