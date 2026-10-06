import hashlib
import json
import unittest
from unittest.mock import patch

from broker import artifact_transport_recovery as recovery, handoffs, test_first_handoffs
from model_policy import MODEL
import test_test_artifact_recovery as fixtures
from test_test_first_handoffs import Effects


class TransportRecoveryTests(unittest.TestCase):
    def test_base_digest_shape_is_not_confused_with_snapshot_record(self):
        self.assertEqual(recovery.baseline_hash('a'*64),'a'*64)
        for bad in ({'sha256':'a'*64,'bytes':10}, '', 'a'*63, 'x'*64, None):
            with self.assertRaises(ValueError):recovery.baseline_hash(bad)

    def test_offline_verifier_pins_import_root_and_readonly_mounts(self):
        task=self.payload['source_task']
        with self.b.db() as con:
            con.execute('ALTER TABLE native_bindings ADD COLUMN issue_id TEXT')
            con.execute('INSERT INTO native_bindings VALUES (?,?,?,?)',(task,'preserved','author',self.f.issue))
        self.b.snapshot_submission=lambda payload,diagnostic: {'volume':'failed-snapshot'}
        configs=[]
        def docker(method,path,data=None):
            if path.startswith('/containers/create'):configs.append(data);return {'Id':'fixture'}
            return {'State':{'Running':False,'ExitCode':0},'Config':{'Labels':{'delivery-kit.owner':self.b.PREFIX+'-integration-verifier-v1'}}}
        self.b.docker=docker
        self.b.docker_stdout=lambda *a,**k: json.dumps({'verified':True,'baseline_unchanged':True,'manifest_sha256':'a'*64})
        with patch('broker.handoff_runtime.task_base',return_value={'volume':'base'}):
            self.assertTrue(recovery.verify_preserved_failure(self.b,task,self.diagnostic)['verified'])
        self.assertEqual(configs[0]['WorkingDir'],'/')
        self.assertEqual(configs[0]['HostConfig']['NetworkMode'],'none')
        self.assertTrue(all(m['ReadOnly'] for m in configs[0]['HostConfig']['Mounts']))

    def setUp(self):
        f = fixtures.ArtifactRecoveryTests(); f.setUp(); self.addCleanup(f.doCleanups)
        f.structural_setup(); f.structural_resume()
        self.f = f; self.b = f.b
        source = '77777777-7777-4777-8777-777777777777'
        with self.b.db() as con:
            prior = handoffs.load(con, f.source); sponsor = json.loads(prior['data'])
            sponsor.update(cto_task=f.cto, decision=f.decision, test_first_correction_wakeup='structural-wake')
            handoffs.save(con, f.source, f.issue, 'test_first_cto_correction_wait', 'author', sponsor, 7)
            self.diagnostic = dict(f.diagnostic, task_id=source)
            handoffs.save(con, source, f.issue, 'test_first_blocked', 'cto',
                          dict(error='test_first_correction_failed_after_cto_diagnosis', diagnostic=self.diagnostic), 8)
        f.runs.append(dict(id=source, agent_id='author', status='completed', created_at='05', wakeup_id='structural-wake'))
        def capture(_):
            (self.b.STATE/'test-first-incidents'/(source+'.json')).write_text(json.dumps(self.diagnostic))
            raise ValueError('test-first NEW test has no executable test methods')
        self.b.capture_test_first_red = capture
        self.proof = dict(schema='acp-artifact-probe-v1', status='passed', model=MODEL,
            worker_image=self.b.IMAGE, proxy_image=f.proxy, delivery_approval=False, product_retry=False,
            prompt_completed=True, fixture_removed=True,
            execution_id='88888888-8888-4888-8888-888888888888',
            inspection=dict(uid=10000, bytes=196, test_methods=1, syntax_valid=True,
                            baseline_unchanged=True, credentials_absent=True, sha256='e'*64))
        self.payload = dict(issue_id=f.issue, source_task=source, probe=self.proof)

    def reopen(self):
        with patch('broker.native.issue_task_runs', return_value=self.f.runs), patch('broker.handoff_runtime.Effects') as effects:
            effects.return_value.decision.return_value = self.f.decision
            return recovery.reopen(self.b, self.payload)

    def test_one_qualified_recovery_preserves_incident_and_dispatches_once(self):
        receipt = self.reopen(); self.assertEqual(receipt, self.reopen())
        self.assertEqual(receipt['diagnostic'], self.diagnostic)
        self.assertEqual(receipt['kind'], 'qualified_acp_response_enforcement_v1')
        with self.b.db() as con:
            prior = handoffs.load(con, self.payload['source_task'])
            self.assertIsNone(con.execute('SELECT 1 FROM test_first_red').fetchone())
        effects = Effects(self.b)
        for _ in range(2):
            test_first_handoffs.technical_recovery(self.b, self.f.route, self.f.runs,
                self.f.runs[-1], prior, effects)
            with self.b.db() as con: prior = handoffs.load(con, self.payload['source_task'])
        self.assertEqual(len(effects.wakeups), 1)
        self.assertEqual(prior['stage'], 'test_first_transport_recovery_wait')
        self.assertIn('independent immutable review', effects.wakeups[0][0][4])

    def test_failed_or_synthetic_probe_and_weakened_inspection_rejected(self):
        for key, value in [('status', 'failed'), ('schema', 'artifact-provider-probe-v1'),
                           ('delivery_approval', True), ('fixture_removed', False)]:
            bad = dict(self.proof, **{key:value})
            with self.assertRaises(ValueError): recovery.validate_probe(bad, self.b.IMAGE)
        for key, value in [('bytes', 0), ('test_methods', 0), ('baseline_unchanged', False), ('credentials_absent', False)]:
            bad = dict(self.proof, inspection=dict(self.proof['inspection'], **{key:value}))
            with self.assertRaises(ValueError): recovery.validate_probe(bad, self.b.IMAGE)

    def test_red_live_worker_and_stale_proxy_rejected(self):
        with self.b.db() as con: con.execute('INSERT INTO test_first_red VALUES (?)', (self.f.issue,))
        with self.assertRaisesRegex(ValueError, 'Red already'): self.reopen()
        with self.b.db() as con:
            con.execute('DELETE FROM test_first_red'); con.execute('INSERT INTO leases VALUES (?)', ('running',))
        with self.assertRaisesRegex(ValueError, 'idle workers'): self.reopen()
        with self.b.db() as con: con.execute('DELETE FROM leases')
        self.proof['proxy_image'] = 'sha256:'+'d'*64
        with self.assertRaisesRegex(ValueError, 'scoped proxy'): self.reopen()

    def test_later_author_or_changed_sponsorship_rejected(self):
        self.f.runs[-1]['wakeup_id'] = 'unrelated'
        with self.assertRaisesRegex(ValueError, 'sponsorship'): self.reopen()
        self.f.runs[-1]['wakeup_id'] = 'structural-wake'
        self.f.runs.append(dict(id='later', agent_id='author', status='completed', created_at='06'))
        with self.assertRaisesRegex(ValueError, 'latest'): self.reopen()

    def test_identity_drift_is_not_an_additional_attempt(self):
        self.reopen()
        self.proof['execution_id'] = '99999999-9999-4999-8999-999999999999'
        with self.assertRaisesRegex(ValueError, 'identity drift'): self.reopen()

    def integration_setup(self):
        self.reopen()
        original = self.payload['source_task']
        failed = '99999999-9999-4999-8999-999999999999'
        execution = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
        with self.b.db() as con:
            prior = handoffs.load(con, original); sponsor = json.loads(prior['data'])
            sponsor['artifact_recovery_wakeup'] = 'transport-wake'
            handoffs.save(con, original, self.f.issue, 'test_first_transport_recovery_wait', 'author', sponsor, 9)
            handoffs.save(con, failed, self.f.issue, 'test_first_blocked', 'cto',
                          dict(error='test_first_correction_failed_after_cto_diagnosis'), 10)
            con.executemany('INSERT INTO native_bindings VALUES (?,?,?)',
                            [(original,'preserved','author'),(failed,'preserved','author')])
            con.execute('ALTER TABLE native_bindings ADD COLUMN request_id TEXT')
            con.execute('UPDATE native_bindings SET request_id=? WHERE task_id=?', (execution,failed))
        self.f.runs.append(dict(id=failed, agent_id='author',status='failed',created_at='06',
            wakeup_id='transport-wake', error='hermes provider error: API call failed after 1 retries'))
        self.f.proxy = 'sha256:'+'d'*64
        proof = dict(self.proof, proxy_image=self.f.proxy)
        self.integration_payload = dict(issue_id=self.f.issue,source_task=failed,probe=proof,
            failure=dict(origin='operator_verified_historical_proxy_metadata',execution_id=execution,
                         call_number=1,status=502,category='wrong_forced_arguments',selected_tool='read_file'))

    def reopen_integration(self, messages=None):
        with patch('broker.native.issue_task_runs',return_value=self.f.runs), patch(
                'broker.native.task_messages',return_value=messages or [{'type':'error'}]), patch(
                'broker.artifact_transport_recovery.verify_preserved_failure',return_value={'verified':True,'baseline_unchanged':True,'manifest_sha256':'a'*64}), patch('broker.handoff_runtime.Effects') as effects:
            effects.return_value.decision.return_value=self.f.decision
            return recovery.reopen_integration(self.b,self.integration_payload)

    def test_integration_repair_is_idempotent_and_preserves_original_artifact(self):
        self.integration_setup(); receipt=self.reopen_integration()
        self.assertEqual(receipt,self.reopen_integration())
        self.assertEqual(receipt['original_source'],self.payload['source_task'])
        self.assertEqual(receipt['diagnostic'],self.diagnostic)
        self.assertTrue(receipt['pretool_verified'])
        effects=Effects(self.b)
        with self.b.db() as con:prior=handoffs.load(con,self.integration_payload['source_task'])
        test_first_handoffs.technical_recovery(self.b,self.f.route,self.f.runs,self.f.runs[-1],prior,effects)
        with self.b.db() as con:
            self.assertEqual(handoffs.load(con,self.integration_payload['source_task'])['stage'],'test_first_integration_recovery_wait')
            self.assertIsNone(con.execute('SELECT 1 FROM test_first_red').fetchone())
        self.assertEqual(len(effects.wakeups),1)

    def test_integration_rejects_tool_activity_same_proxy_or_wrong_failure_binding(self):
        self.integration_setup()
        with self.assertRaisesRegex(ValueError,'tool activity'):self.reopen_integration([{'type':'tool_use'}])
        self.integration_payload['failure']['execution_id']='bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'
        with self.assertRaisesRegex(ValueError,'binding'):self.reopen_integration()
        self.integration_payload['failure']['execution_id']='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
        self.integration_payload['probe']['proxy_image']=self.proof['proxy_image']
        with self.assertRaisesRegex(ValueError,'changed qualified'):self.reopen_integration()

    def test_integration_rejects_changed_workspace_and_historical_provenance(self):
        self.integration_setup()
        self.integration_payload['failure']['origin']='proxy_receipt'
        with self.assertRaisesRegex(ValueError,'historical'):self.reopen_integration()
        self.integration_payload['failure']['origin']='operator_verified_historical_proxy_metadata'
        with self.b.db() as con:con.execute('UPDATE native_bindings SET scope=? WHERE task_id=?',('other',self.integration_payload['source_task']))
        with self.assertRaisesRegex(ValueError,'workspace'):self.reopen_integration()

    def compact_setup(self):
        self.integration_setup(); self.reopen_integration()
        previous = self.integration_payload['source_task']
        failed = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'
        execution = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc'
        with self.b.db() as con:
            prior = handoffs.load(con, previous); sponsor = json.loads(prior['data'])
            sponsor['artifact_recovery_wakeup'] = 'integration-wake'
            handoffs.save(con, previous, self.f.issue, 'test_first_integration_recovery_wait', 'author', sponsor, 11)
            handoffs.save(con, failed, self.f.issue, 'test_first_blocked', 'cto',
                          dict(error='test_first_correction_failed_after_cto_diagnosis'), 12)
            con.execute('INSERT INTO native_bindings VALUES (?,?,?,?)',(failed,'preserved','author',execution))
        self.f.runs.append(dict(id=failed, agent_id='author', status='failed', created_at='07',
            wakeup_id='integration-wake', error='hermes provider error: API call failed after 1 retries'))
        self.f.proxy = 'sha256:'+'f'*64
        self.integration_payload = dict(issue_id=self.f.issue,source_task=failed,
            probe=dict(self.proof,proxy_image=self.f.proxy),
            failure=dict(origin='operator_verified_historical_proxy_metadata',execution_id=execution,
                call_number=2,status=502,category='invalid_response_encoding',selected_tool='write_file',
                completion_tokens=8192,output_limit=8192,finish_reason='tool_calls'))
        self.reads = [{'type':'tool_result','tool':'read_file',
                       'output':'Read /workspace/app.py — 1 total lines\n\nVALUE = 0'}]

    def test_compact_write_replan_is_not_pretool_and_dispatches_once(self):
        self.compact_setup(); receipt = self.reopen_integration(self.reads)
        self.assertEqual(receipt,self.reopen_integration(self.reads))
        self.assertFalse(receipt['pretool_verified']); self.assertTrue(receipt['postread_verified'])
        self.assertEqual(receipt['repair_kind'],'post_read_compact_write_replan_v1')
        self.assertFalse(receipt['recovery_policy']['truncation_proven'])
        effects=Effects(self.b)
        for _ in range(2):
            with self.b.db() as con:prior=handoffs.load(con,self.integration_payload['source_task'])
            test_first_handoffs.technical_recovery(self.b,self.f.route,self.f.runs,self.f.runs[-1],prior,effects)
        self.assertEqual(len(effects.wakeups),1)
        self.assertIn('ALL unchanged acceptance',effects.wakeups[0][0][4])
        with self.b.db() as con:self.assertIsNone(con.execute('SELECT 1 FROM test_first_red').fetchone())

    def test_compact_rejects_missing_reads_writes_and_other_tools(self):
        self.compact_setup()
        for messages in ([{'type':'error'}], self.reads+[{'type':'tool_use','tool':'write_file'}],
                         self.reads+[{'type':'tool_use','tool':'terminal'}],
                         self.reads+[{'type':'tool_result','tool':'edit_file','output':'done'}],
                         self.reads+[{'tool_calls':[{'name':'write_file'}]}],
                         self.reads+[{'type':'tool_result','tool':'read_file','output':'unclassified'}]):
            with self.assertRaisesRegex(ValueError,'without writes'):self.reopen_integration(messages)

    def test_compact_rejects_unobserved_budget_or_same_proxy(self):
        self.compact_setup(); self.integration_payload['failure']['completion_tokens']=8191
        with self.assertRaisesRegex(ValueError,'boundary'):self.reopen_integration(self.reads)
        self.integration_payload['failure']['completion_tokens']=8192
        self.integration_payload['probe']['proxy_image']='sha256:'+'d'*64
        with self.assertRaisesRegex(ValueError,'changed qualified'):self.reopen_integration(self.reads)

    def test_compact_failure_class_cannot_repeat_on_new_execution(self):
        self.compact_setup(); self.reopen_integration(self.reads)
        other='dddddddd-dddd-4ddd-8ddd-dddddddddddd'
        with self.b.db() as con:handoffs.save(con,other,self.f.issue,'test_first_blocked','cto',{},13)
        self.integration_payload['source_task']=other
        with self.assertRaisesRegex(ValueError,'class repair already consumed'):self.reopen_integration(self.reads)
