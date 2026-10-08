import json
import sqlite3
import unittest
from unittest.mock import Mock,patch
import test_product_scope_pipeline as fixtures
from broker import product_scope_pipeline as pipeline,product_scope_ledger as ledger
from broker import product_scope_envelope_recovery as recovery


class ScopeEnvelopeRecoveryTests(unittest.TestCase):
    def setUp(self):
        f=fixtures.ProductScopePipelineTests();f.setUp();self.addCleanup(f.doCleanups)
        self.b,self.issue=f.b,f.issue
        pipeline.register(self.b,f.config);f.tick()
        with self.b.db() as con:
            original=json.loads(con.execute('SELECT data FROM product_scope_plans').fetchone()[0])['original_contract']
            p=ledger.open_plan(con,original,dict(f.context,issue_id=self.issue))
            self.old=ledger.save_transition(con,p,dict(p,stage='blocked',incident=dict(
                category='invalid_scope_proposal',task_id='failed',owner='cto',automatic_retry=False)))
        before=f.state()
        self.run=pipeline.save(self.b,self.issue,before,dict(before,stage='blocked',plan_key=p['key'],
                incident=dict(category='scope_plan_not_approved',owner='cto',automatic_retry=False)))
        self.proof=dict(operation='qualified_scope_envelope_recovery_v1',failed_task='failed',
            original_plan_sha256=ledger.policy.digest(self.old),envelope_sha256='a'*64,
            decoder_sha256='b'*64,prompt_sha256='c'*64,write_grant_issued=False,delivery_approval=False)
        self.fx=Mock();self.fx.qualify.return_value=self.proof

    def test_new_lineage_preserves_failure_and_resumes_without_dispatch_or_authority(self):
        new=recovery.recover(self.b,self.issue,self.fx)
        self.assertNotEqual(new['key'],self.old['key'])
        self.assertEqual(new['context'],self.old['context'])
        self.assertEqual(new['stage'],'awaiting_proposal')
        self.assertTrue(new['author_blocked']);self.assertFalse(new['delivery_approval'])
        self.assertNotIn('dispatch',new)
        with self.b.db() as con:
            self.assertEqual(ledger.load(con,self.old['key']),self.old)
            run=json.loads(con.execute('SELECT state FROM product_scope_runs WHERE issue_id=?',(self.issue,)).fetchone()[0])
        self.assertEqual(run['previous_incident'],self.run['incident'])
        self.assertEqual(run['plan_key'],new['key'])
        self.assertEqual(recovery.recover(self.b,self.issue,self.fx),new)
        self.fx.qualify.assert_called_once_with(self.old)
        self.fx.wake.assert_not_called()

    def test_changed_proof_or_claimed_approval_cannot_reopen(self):
        for mutation in ({'delivery_approval':True},{'failed_task':'other'},{'decoder_sha256':'unverified'},
                         {'original_plan_sha256':'0'*64},{'write_grant_issued':True}):
            with self.subTest(mutation=mutation):
                self.fx.qualify.return_value=dict(self.proof,**mutation)
                with self.assertRaises(ValueError):recovery.recover(self.b,self.issue,self.fx)
                with self.b.db() as con:self.assertEqual(ledger.load(con,self.old['key']),self.old)

    def test_sponsor_change_during_probe_rejects_recovery(self):
        def change(plan):
            with self.b.db() as con:
                con.execute('UPDATE product_scope_runs SET state=?',(ledger.encoded(dict(self.run,source_task='other')),))
            return self.proof
        self.fx.qualify.side_effect=change
        with self.assertRaises(ValueError):recovery.recover(self.b,self.issue,self.fx)

    def test_functional_or_approved_failures_do_not_use_envelope_recovery(self):
        with self.b.db() as con:
            wrong=dict(self.old,incident=dict(self.old['incident'],category='invalid_scope_review'))
            ledger.save_transition(con,self.old,wrong)
        with self.assertRaises(ValueError):recovery.recover(self.b,self.issue,self.fx)
        self.fx.qualify.assert_not_called()

    def native_effects(self):
        fx=object.__new__(recovery.NativeEffects);fx.b=self.b
        fx.verify_binding=Mock()
        fx.task=Mock(return_value=dict(id='failed',status='failed',error=recovery.ERROR,issue_id=self.issue,
                    scope_note_envelope_verified=True,scope_note_envelope_sha256='a'*64))
        with self.b.db() as con:
            con.executescript('CREATE TABLE native_bindings(request_id TEXT,task_id TEXT);'
                             'CREATE TABLE acp_events(request_id TEXT,method TEXT,success INTEGER);')
            con.execute('INSERT INTO native_bindings VALUES (?,?)',('request','failed'))
            con.executemany('INSERT INTO acp_events VALUES (?,?,?)',[('request','initialize',1),('request','session/new',1)])
        return fx

    def test_native_qualification_requires_failed_envelope_and_only_pre_prompt_events(self):
        fx=self.native_effects()
        with patch.object(recovery.execution,'prompt',return_value='fixed exact note') as prompt:
            proof=fx.qualify(self.old)
            self.assertFalse(proof['delivery_approval'])
            self.assertFalse(proof['write_grant_issued'])
            probe=prompt.call_args.args[0]
            with self.assertRaises(sqlite3.ProgrammingError):
                with probe.db() as con:con.execute('SELECT 1')
        with self.b.db() as con:con.execute('INSERT INTO acp_events VALUES (?,?,?)',('request','session/prompt',1))
        with self.assertRaises(ValueError):fx.qualify(self.old)

    def test_native_qualification_rejects_completed_task_or_missing_envelope(self):
        fx=self.native_effects()
        for mutation in ({'status':'completed'},{'scope_note_envelope_verified':False},{'error':'functional failure'}):
            original=dict(fx.task.return_value)
            fx.task.return_value=dict(original,**mutation)
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):fx.qualify(self.old)
            fx.task.return_value=original
