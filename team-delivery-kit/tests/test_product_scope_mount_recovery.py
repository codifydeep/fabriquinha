import json
import unittest
from unittest.mock import Mock,patch
import test_product_scope_envelope_recovery as fixtures
from broker import product_scope_mount_recovery as recovery,product_scope_ledger as ledger
from broker import product_scope_pipeline as pipeline


class ScopeMountRecoveryTests(unittest.TestCase):
    def setUp(self):
        f=fixtures.ScopeEnvelopeRecoveryTests();f.setUp();self.addCleanup(f.doCleanups)
        self.b,self.issue=f.b,f.issue
        proposal=dict(operation='propose_product_scope_revision_v1',reason='Required dependency',write_files=['app/db.py'],
                      **{k:f.old['context'][k] for k in ('issue_id','source_task','contract_sha256','snapshot_sha256','failure_output_sha256')})
        with self.b.db() as con:
            self.old=ledger.save_transition(con,f.old,dict(f.old,proposal=proposal,proposal_sha256=ledger.policy.digest(proposal),
                proposal_task=dict(id='cto-task',agent_id='cto',issue_id=self.issue,status='completed'),
                incident=dict(category='invalid_scope_review',task_id='failed-review',owner='lead',automatic_retry=False)))
        self.proof=dict(operation='qualified_scope_mount_recovery_v1',failed_task='failed-review',
            original_plan_sha256=ledger.policy.digest(self.old),proposal_sha256=self.old['proposal_sha256'],
            failed_payload_sha256='a'*64,mount_sha256='b'*64,write_grant_issued=False,delivery_approval=False)
        self.fx=Mock();self.fx.qualify.return_value=self.proof

    def test_resume_only_review_preserves_completed_proposal_and_failed_plan(self):
        new=recovery.recover(self.b,self.issue,self.fx)
        self.assertEqual(new['stage'],'awaiting_review');self.assertNotEqual(new['key'],self.old['key'])
        for key in ('proposal','proposal_sha256','proposal_task','context','original_contract'):
            self.assertEqual(new[key],self.old[key])
        self.assertTrue(new['author_blocked']);self.assertFalse(new['delivery_approval'])
        self.assertNotIn('dispatch',new);self.assertNotIn('review',new)
        with self.b.db() as con:self.assertEqual(ledger.load(con,self.old['key']),self.old)
        self.assertEqual(recovery.recover(self.b,self.issue,self.fx),new)
        self.fx.qualify.assert_called_once();self.fx.wake.assert_not_called()

    def test_invalid_proof_or_changed_proposal_cannot_resume(self):
        for mutation in ({'delivery_approval':True},{'proposal_sha256':'0'*64},{'failed_task':'other'},
                         {'original_plan_sha256':'0'*64},{'mount_sha256':'text'}):
            with self.subTest(mutation=mutation):
                self.fx.qualify.return_value=dict(self.proof,**mutation)
                with self.assertRaises(ValueError):recovery.recover(self.b,self.issue,self.fx)
        with self.b.db() as con:
            ledger.save_transition(con,self.old,dict(self.old,proposal=dict(self.old['proposal'],write_files=['tests/test.py'])))
        with self.assertRaises(ValueError):recovery.recover(self.b,self.issue,self.fx)

    def test_failed_proposal_or_existing_approval_never_uses_mount_recovery(self):
        with self.b.db() as con:ledger.save_transition(con,self.old,dict(self.old,qualification=dict(status='plan_approved')))
        with self.assertRaises(ValueError):recovery.recover(self.b,self.issue,self.fx)
        self.fx.qualify.assert_not_called()

    def native_effects(self):
        fx=object.__new__(recovery.NativeEffects);fx.b=self.b;self.b.OWNER='owner'
        fx.verify_binding=Mock();fx.read_hashes=Mock(return_value=self.old['context']['eligible_code_sha256'])
        proposal=dict(self.old['proposal_task'],result=dict(output=json.dumps(self.old['proposal'])))
        failed=dict(id='failed-review',agent_id='lead',issue_id=self.issue,status='failed',error=recovery.ERROR)
        fx.task=Mock(side_effect=[proposal,failed])
        payload=dict(Image='worker',Labels={'delivery-kit.owner':'owner'},HostConfig=dict(Mounts=[]))
        sha=recovery.hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()
        observation=dict(operation='worker_policy_observation_v1',request_id='request',payload_sha256=sha,
                         worker_image='worker',normalized_differences=[])
        with self.b.db() as con:
            con.executescript('CREATE TABLE native_bindings(request_id TEXT,task_id TEXT);'
                'CREATE TABLE worker_creation_intents(request_id TEXT,payload TEXT);'
                'CREATE TABLE leases(request_id TEXT,status TEXT);'
                'CREATE TABLE worker_policy_observations(request_id TEXT,receipt TEXT);')
            con.execute('INSERT INTO native_bindings VALUES (?,?)',('request','failed-review'))
            con.execute('INSERT INTO worker_creation_intents VALUES (?,?)',('request',json.dumps(payload)))
            con.execute('INSERT INTO leases VALUES (?,?)',('request','closed'))
            con.execute('INSERT INTO worker_policy_observations VALUES (?,?)',('request',json.dumps(observation)))
        return fx

    def test_native_qualification_uses_readonly_isolated_resolver_and_authenticates_proposal(self):
        fx=self.native_effects()
        expected=[dict(Type='volume',Source='snapshot',Target='/evidence/candidate',ReadOnly=True)]
        with patch.object(recovery.revision,'planning_mounts',return_value=expected) as resolver:
            proof=fx.qualify(self.old)
            self.assertFalse(proof['delivery_approval'])
            probe=resolver.call_args.args[0]
            with self.assertRaises(ValueError):probe.docker('POST','/containers/create',{})
        fx.verify_binding.assert_called_with(self.old)

    def test_missing_observation_or_already_mounted_candidate_rejected(self):
        fx=self.native_effects()
        with self.b.db() as con:con.execute('DELETE FROM worker_policy_observations')
        with self.assertRaises(ValueError):fx.qualify(self.old)

    def test_candidate_mount_present_is_not_missing_mount_recovery(self):
        fx=self.native_effects()
        with self.b.db() as con:
            raw=con.execute('SELECT payload FROM worker_creation_intents').fetchone()[0];payload=json.loads(raw)
            payload['HostConfig']['Mounts']=[dict(Target='/evidence/candidate',Source='snapshot',ReadOnly=True)]
            con.execute('UPDATE worker_creation_intents SET payload=?',(json.dumps(payload),))
        with self.assertRaises(ValueError):fx.qualify(self.old)

    def test_normal_loop_recovers_once_without_operator_handoff(self):
        with patch.object(pipeline.controller_maintenance,'current',return_value=None),\
                patch.object(recovery,'NativeEffects',return_value=self.fx):
            self.assertEqual(pipeline.tick(self.b),{self.issue})
            with patch.object(pipeline.execution,'tick') as execution:
                pipeline.tick(self.b);execution.assert_called_once()
        self.fx.qualify.assert_called_once()
        with self.b.db() as con:
            state=json.loads(con.execute('SELECT state FROM product_scope_runs WHERE issue_id=?',(self.issue,)).fetchone()[0])
        self.assertEqual(state['stage'],'scope_plan')
        self.assertFalse(state['delivery_approval'])

    def test_failed_qualification_remains_visible_without_identical_automatic_retry(self):
        self.fx.qualify.side_effect=ValueError('not a proven missing mount')
        with patch.object(pipeline.controller_maintenance,'current',return_value=None),\
                patch.object(recovery,'NativeEffects',return_value=self.fx):
            pipeline.tick(self.b);pipeline.tick(self.b)
        self.fx.qualify.assert_called_once()
        with self.b.db() as con:state=json.loads(con.execute('SELECT state FROM product_scope_runs').fetchone()[0])
        self.assertEqual(state['stage'],'blocked')
        self.assertEqual(state['scope_mount_recovery_attempt']['stage'],'rejected')
        self.assertFalse(state['scope_mount_recovery_attempt']['automatic_retry'])

    def test_restart_after_qualifying_intent_resumes_same_plan_not_starvation(self):
        with self.b.db() as con:
            state=json.loads(con.execute('SELECT state FROM product_scope_runs').fetchone()[0])
            con.execute('UPDATE product_scope_runs SET state=?',(ledger.encoded(dict(state,scope_mount_recovery_attempt=dict(stage='qualifying'))),))
        with patch.object(pipeline.controller_maintenance,'current',return_value=None),\
                patch.object(recovery,'NativeEffects',return_value=self.fx):
            pipeline.tick(self.b)
        self.fx.qualify.assert_called_once()
        with self.b.db() as con:state=json.loads(con.execute('SELECT state FROM product_scope_runs').fetchone()[0])
        self.assertEqual(state['stage'],'scope_plan')
