import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from broker import handoffs, test_artifact_recovery, test_first_handoffs
from test_test_first_handoffs import Broker, Effects


class ArtifactRecoveryTests(unittest.TestCase):
    def framework_setup(self):
        self.diagnostic=dict(issue_id=self.issue,task_id=self.source,kind='rejected_red',
            exit_code=1,command=['python3','-m','unittest','discover','-s','.','-q'],
            manifest_sha256='b'*64,test_sha256={'tests/test_new.py':'c'*64},
            output_excerpt="ModuleNotFoundError: No module named 'pytest'",
            output_sha256='d'*64)
        path=self.b.STATE/'test-first-incidents';path.mkdir()
        (path/(self.source+'.json')).write_text(json.dumps(self.diagnostic))
        self.data['diagnostic']=self.diagnostic
        self.data['historical_context']='h'*20000
        with self.b.db() as c:
            handoffs.save(c,self.source,self.issue,'test_first_blocked','cto',self.data,2)
        self.framework_payload=dict(issue_id=self.issue,source_task=self.source,worker_image=self.b.IMAGE)

    def framework_resume(self):
        with patch('broker.native.issue_task_runs',return_value=self.runs),patch(
                'broker.handoff_runtime.Effects') as adapter,patch(
                'broker.artifact_transport_recovery.verify_preserved_failure',return_value={
                    'verified':True,'baseline_unchanged':True,'framework_mismatch':True,
                    'task_id':self.source,'manifest_sha256':'b'*64,'volume':'frozen'}):
            adapter.return_value.decision.return_value=self.decision
            return test_artifact_recovery.replan_framework(self.b,self.framework_payload)

    def test_framework_replan_is_preserved_bound_and_cto_only(self):
        self.framework_setup()
        receipt=self.framework_resume()
        self.assertEqual(receipt,self.framework_resume())
        self.assertEqual(receipt['previous_blocker'],self.data)
        with self.b.db() as c:prior=handoffs.load(c,self.source)
        effects=Effects(self.b)
        test_first_handoffs.technical_recovery(self.b,self.route,self.runs,self.runs[0],prior,effects)
        self.assertEqual(len(effects.wakeups),1)
        self.assertEqual(effects.wakeups[0][0][1],'cto')
        self.assertIn('pytest import',effects.wakeups[0][0][4])
        self.assertIn('preserve all assertions',effects.wakeups[0][0][4])
        self.assertLess(len(effects.wakeups[0][0][4]),6000)
        self.assertNotIn(self.data['historical_context'],effects.wakeups[0][0][4])

    def test_framework_replan_rejects_unrelated_failure_and_source(self):
        self.framework_setup()
        self.runs[0]['wakeup_id']='other'
        with self.assertRaisesRegex(ValueError,'sponsorship'):self.framework_resume()
        self.runs[0]['wakeup_id']='correction'
        self.diagnostic['exit_code']=0
        (self.b.STATE/'test-first-incidents'/(self.source+'.json')).write_text(json.dumps(self.diagnostic))
        with self.assertRaisesRegex(ValueError,'diagnostic'):self.framework_resume()

    def test_framework_replan_requires_idle_workers_and_no_red(self):
        self.framework_setup()
        with self.b.db() as c:c.execute('INSERT INTO leases VALUES (?)',('running',))
        with self.assertRaisesRegex(ValueError,'idle'):self.framework_resume()
        with self.b.db() as c:
            c.execute('DELETE FROM leases');c.execute('INSERT INTO test_first_red VALUES (?)',(self.issue,))
        with self.assertRaisesRegex(ValueError,'Red exists'):self.framework_resume()

    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.b = Broker(Path(temp.name) / 'state.sqlite')
        self.b.STATE = Path(temp.name); self.b.LOCK = threading.RLock()
        self.b.IMAGE = 'sha256:' + 'a' * 64
        (self.b.STATE / 'native.json').write_text('{}')
        self.issue = '11111111-1111-4111-8111-111111111111'
        self.source = '22222222-2222-4222-8222-222222222222'
        self.cto = '33333333-3333-4333-8333-333333333333'
        self.payload = dict(issue_id=self.issue, source_task=self.source, cto_task=self.cto, worker_image=self.b.IMAGE)
        self.route = dict(issue_id=self.issue, enabled=True, test_first=True, author='author', cto='cto',
                          minimum_calls=8, test_first_files=['tests/test_new.py'])
        self.decision = dict(action='request_correction', optional_files=[], reason='Write the actual NEW test.')
        self.data = dict(phase='test_first', error='test_first_correction_failed_after_cto_diagnosis')
        self.diagnostic = dict(issue_id=self.issue, task_id=self.source, kind='rejected_snapshot', category='empty_new_test',
                               files={'tests/test_new.py': dict(bytes=0, sha256=hashlib.sha256(b'').hexdigest())})
        self.runs = [dict(id=self.source, agent_id='author', status='completed', created_at='02', wakeup_id='correction'),
                     dict(id=self.cto, agent_id='cto', status='completed', created_at='01')]
        self.b.test_artifact_phase_context = lambda *_: '\nDELIVERY_TEST_ARTIFACT_V1:/workspace/tests/test_new.py\n'
        self.probes = 0
        def capture(_):
            self.probes += 1
            path = self.b.STATE / 'test-first-incidents'; path.mkdir(exist_ok=True)
            (path / (self.source + '.json')).write_text(json.dumps(self.diagnostic))
            raise ValueError('empty test')
        self.b.capture_test_first_red = capture
        with self.b.db() as c:
            handoffs.initialize(c)
            c.execute('CREATE TABLE test_first_red(issue_id TEXT)')
            c.execute('CREATE TABLE leases(status TEXT)')
            c.execute('INSERT INTO delivery_routes VALUES (?,?)', (self.issue, json.dumps(self.route)))
            handoffs.save(c, 'old', self.issue, 'test_first_cto_correction_wait', 'author',
                          dict(cto_task=self.cto, test_first_correction_wakeup='correction', decision=self.decision), 1)
            handoffs.save(c, self.source, self.issue, 'test_first_blocked', 'cto', self.data, 2)

    def reopen(self):
        with patch('broker.native.issue_task_runs', return_value=self.runs), patch(
                'broker.handoff_runtime.Effects') as effects:
            effects.return_value.decision.return_value = self.decision
            return test_artifact_recovery.reopen(self.b, self.payload)

    def test_preserves_failure_probes_once_and_dispatches_idempotently(self):
        receipt = self.reopen(); self.assertEqual(receipt, self.reopen())
        self.assertEqual(self.probes, 1); self.assertEqual(receipt['previous_blocker'], self.data)
        effects = Effects(self.b)
        with self.b.db() as c: prior = handoffs.load(c, self.source)
        test_first_handoffs.technical_recovery(self.b, self.route, self.runs, self.runs[0], prior, effects)
        with self.b.db() as c:
            prior = handoffs.load(c, self.source)
            self.assertIsNone(c.execute('SELECT 1 FROM test_first_red').fetchone())
        self.assertEqual(prior['stage'], 'test_first_artifact_recovery_wait')
        test_first_handoffs.technical_recovery(self.b, self.route, self.runs, self.runs[0], prior, effects)
        self.assertEqual(len(effects.wakeups), 1)
        self.assertIn('actual write_file', effects.wakeups[0][0][4])

    def test_rejects_disabled_gate_or_different_image(self):
        self.b.test_artifact_phase_context = lambda *_: ''
        with self.assertRaisesRegex(ValueError, 'enabled'): self.reopen()
        self.payload['worker_image'] = 'sha256:' + 'b' * 64
        with self.assertRaisesRegex(ValueError, 'immutable'): self.reopen()

    def test_rejects_live_worker_red_and_later_author(self):
        with self.b.db() as c: c.execute('INSERT INTO leases VALUES (?)', ('starting',))
        with self.assertRaisesRegex(ValueError, 'idle workers'): self.reopen()
        with self.b.db() as c:
            c.execute('DELETE FROM leases'); c.execute('INSERT INTO test_first_red VALUES (?)', (self.issue,))
        with self.assertRaisesRegex(ValueError, 'Red already'): self.reopen()
        with self.b.db() as c: c.execute('DELETE FROM test_first_red')
        self.runs.append(dict(id='later', agent_id='author', status='completed', created_at='03'))
        with self.assertRaisesRegex(ValueError, 'latest'): self.reopen()

    def test_rejects_stale_sponsorship_or_nonempty_snapshot(self):
        self.runs[0]['wakeup_id'] = 'different'
        with self.assertRaisesRegex(ValueError, 'sponsorship'): self.reopen()
        self.runs[0]['wakeup_id'] = 'correction'
        self.diagnostic['files']['tests/test_new.py']['bytes'] = 1
        with self.assertRaisesRegex(ValueError, 'snapshot evidence'): self.reopen()
        with self.b.db() as c:
            self.assertEqual(handoffs.load(c, self.source)['stage'], 'test_first_blocked')

    def test_rejects_second_recovery_for_same_issue_and_identity_drift(self):
        self.reopen()
        self.payload['worker_image'] = 'sha256:' + 'b' * 64
        self.b.IMAGE = self.payload['worker_image']
        with self.assertRaisesRegex(ValueError, 'identity drift'): self.reopen()
        self.payload['source_task'] = '44444444-4444-4444-8444-444444444444'
        with self.b.db() as c:
            handoffs.save(c, self.payload['source_task'], self.issue, 'test_first_blocked', 'cto', self.data, 3)
        with self.assertRaisesRegex(ValueError, 'already consumed'): self.reopen()

    def provider_setup(self):
        self.reopen()
        failed = '55555555-5555-4555-8555-555555555555'
        self.b.PREFIX = 'delivery-kit-port2'
        self.proxy = 'sha256:' + 'f' * 64
        self.b.docker = lambda *_: {'Image': self.proxy, 'State': {'Running': True},
            'Config': {'Labels': {'com.docker.compose.project': self.b.PREFIX}}}
        self.runs.append(dict(id=failed, agent_id='author', status='failed', created_at='03',
            wakeup_id='artifact', error='hermes provider error: API call failed after 1 retries'))
        with self.b.db() as c:
            prior = handoffs.load(c, self.source); data = json.loads(prior['data'])
            data['artifact_recovery_wakeup'] = 'artifact'
            handoffs.save(c, self.source, self.issue, 'test_first_artifact_recovery_wait', 'author', data, 3)
            handoffs.save(c, failed, self.issue, 'test_first_blocked', 'cto', self.data, 4)
            c.execute('CREATE TABLE native_bindings(task_id TEXT,scope TEXT,agent_id TEXT)')
            c.executemany('INSERT INTO native_bindings VALUES (?,?,?)',
                          [(self.source,'scope','author'),(failed,'scope','author')])
        from model_policy import MODEL
        self.provider_payload = {'issue_id': self.issue, 'failed_task': failed, 'probe': {
            'schema': 'artifact-provider-probe-v1', 'status': 'passed', 'model': MODEL,
            'executed': False, 'delivery_approval': False, 'gate_sha256': 'a'*64,
            'proxy_image': self.proxy, 'phases': [{'phase':'read','arguments_valid':True},
                                                {'phase':'write','arguments_valid':True}]}}

    def provider_resume(self, messages=None):
        with patch('broker.native.issue_task_runs', return_value=self.runs), patch(
                'broker.native.task_messages', return_value=messages or [{'type':'error'}]):
            return test_artifact_recovery.reopen_provider(self.b, self.provider_payload)

    def test_provider_recovery_is_one_changed_transport_not_artifact_budget_reset(self):
        self.provider_setup()
        result = self.provider_resume(); self.assertEqual(result, self.provider_resume())
        self.assertEqual(result['original_source'], self.source)
        with self.b.db() as c: prior = handoffs.load(c, self.provider_payload['failed_task'])
        effects = Effects(self.b)
        test_first_handoffs.technical_recovery(self.b, self.route, self.runs, self.runs[-1], prior, effects)
        self.assertEqual(len(effects.wakeups), 1)
        with self.b.db() as c:
            self.assertEqual(handoffs.load(c,self.provider_payload['failed_task'])['stage'], 'test_first_provider_recovery_wait')
            self.assertIsNone(c.execute('SELECT 1 FROM test_first_red').fetchone())

    def test_provider_recovery_rejects_tools_stale_image_and_changed_workspace(self):
        self.provider_setup()
        with self.assertRaisesRegex(ValueError,'tool activity'):
            self.provider_resume([{'type':'tool_use'}])
        self.proxy = 'sha256:' + 'e'*64
        with self.assertRaisesRegex(ValueError,'installed scoped proxy'): self.provider_resume()
        self.proxy = self.provider_payload['probe']['proxy_image']
        with self.b.db() as c: c.execute('UPDATE native_bindings SET scope=? WHERE task_id=?',
            ('other',self.provider_payload['failed_task']))
        with self.assertRaisesRegex(ValueError,'preserved author workspace'): self.provider_resume()

    def test_provider_recovery_rejects_failed_probe_and_wrong_native_error(self):
        self.provider_setup()
        self.provider_payload['probe']['status'] = 'failed'
        with self.assertRaisesRegex(ValueError,'successful bound'): self.provider_resume()
        self.provider_payload['probe']['status'] = 'passed'
        self.runs[-1]['error'] = 'task timed out'
        with self.assertRaisesRegex(ValueError,'pre-tool provider failure'): self.provider_resume()

    def structural_setup(self):
        self.provider_setup(); receipt = self.provider_resume()
        current = '66666666-6666-4666-8666-666666666666'
        with self.b.db() as c:
            prior = handoffs.load(c, self.provider_payload['failed_task']); data = json.loads(prior['data'])
            data['artifact_recovery_wakeup'] = 'provider-correction'
            handoffs.save(c, self.provider_payload['failed_task'], self.issue, 'test_first_provider_recovery_wait', 'author', data, 5)
            handoffs.save(c, current, self.issue, 'test_first_blocked', 'cto', self.data, 6)
        self.runs.append(dict(id=current,agent_id='author',status='completed',created_at='04',wakeup_id='provider-correction'))
        self.source = current
        self.diagnostic = dict(issue_id=self.issue,task_id=current,kind='rejected_snapshot',category='new_test_no_methods',
            files={'tests/test_new.py':dict(bytes=123,sha256='b'*64)})
        self.structural_payload = dict(issue_id=self.issue,source_task=current,worker_image=self.b.IMAGE)
        def capture(_):
            self.probes += 1
            (self.b.STATE/'test-first-incidents'/(current+'.json')).write_text(json.dumps(self.diagnostic))
            raise ValueError('test-first NEW test has no executable test methods')
        self.b.capture_test_first_red = capture

    def structural_resume(self):
        with patch('broker.native.issue_task_runs',return_value=self.runs):
            return test_artifact_recovery.replan_structure(self.b,self.structural_payload)

    def test_structural_replan_preserves_old_attempts_and_dispatches_new_cto_once(self):
        self.structural_setup(); receipt=self.structural_resume()
        self.assertEqual(receipt,self.structural_resume())
        with self.b.db() as c:prior=handoffs.load(c,self.source)
        effects=Effects(self.b)
        test_first_handoffs.technical_recovery(self.b,self.route,self.runs,self.runs[-1],prior,effects)
        self.assertEqual(len(effects.wakeups),1)
        self.assertEqual(effects.wakeups[0][0][1],'cto')
        self.assertIn('zero test_ methods',effects.wakeups[0][0][4])
        with self.b.db() as c:
            prior=handoffs.load(c,self.source)
            self.assertEqual(prior['stage'],'test_first_cto_diagnosis')
        test_first_handoffs.technical_recovery(self.b,self.route,self.runs,self.runs[-1],prior,effects)
        self.assertEqual(len(effects.wakeups),1)

    def test_structural_replan_rejects_stale_or_changed_snapshot(self):
        self.structural_setup()
        self.runs[-1]['wakeup_id']='unrelated'
        with self.assertRaisesRegex(ValueError,'latest provider-repaired'):self.structural_resume()
        self.runs[-1]['wakeup_id']='provider-correction'
        self.diagnostic['category']='empty_new_test'
        with self.assertRaisesRegex(ValueError,'no-methods snapshot'):self.structural_resume()
        self.diagnostic['category']='new_test_no_methods'
        self.b.capture_test_first_red=lambda _:(_ for _ in ()).throw(ValueError('test-first incident identity drift'))
        with self.assertRaisesRegex(ValueError,'identity drift'):self.structural_resume()
