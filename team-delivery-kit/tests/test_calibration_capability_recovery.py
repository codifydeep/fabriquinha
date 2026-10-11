import copy
import json
import unittest
from broker import generic_calibration_capability_recovery as repair,handoffs
from generic_harness_calibration import digest
import test_generic_calibration_protocol_recovery as samples


class CapabilityRecoveryTests(unittest.TestCase):
    def setUp(self):
        fixture=samples.ProtocolRecoveryTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        self.f=fixture;self.con=fixture.con;self.c=fixture.c
        self.c['prepared']=dict(manifest_sha256='c'*64,test_sha256={'tests/test_one.py':'d'*64})
        self.con.execute('UPDATE generic_calibration_workflows SET config=?',(json.dumps(self.c),));self.con.commit()
        self.proof=dict(operation='generic_calibration_multipath_seam_v1',candidate_manifest_sha256='c'*64,
            test_sha256=self.c['prepared']['test_sha256'],paths={'tests/test_one.py':{'APP_JS':'app/app.js','INDEX_HTML':'app/index.html'}},
            product_sha256={'app/app.js':'e'*64,'app/index.html':'f'*64},tests_executed=False,execution_authorized=False,delivery_approval=False)

    def migrate(self,**overrides):
        c,s=map(json.loads,self.con.execute('SELECT config,state FROM generic_calibration_workflows').fetchone())
        args=dict(con=self.con,c=c,state=s,task=self.f.t,binding=self.f.b,proof=self.proof,
            barrier=self.f.barrier,namespace='delivery-kit-port2',now=1)
        args.update(overrides);return repair.transition(**args)

    def test_one_capability_change_preserves_failure_and_all_delivery_authority(self):
        receipt=self.migrate();c,s=map(json.loads,self.con.execute('SELECT config,state FROM generic_calibration_workflows').fetchone())
        self.assertEqual(c,{**self.c,'calibration_engine':'unittest_path_fixtures_v2'})
        self.assertEqual(receipt['prior_config'],self.c);self.assertEqual(receipt['prior_state'],self.f.s)
        self.assertEqual(s['stage'],'bundle_dispatch');self.assertEqual(s['capability_recovery_sha256'],digest(receipt))
        self.assertFalse(receipt['author_restarted']);self.assertFalse(receipt['delivery_approval'])
        self.assertEqual(self.migrate(),receipt)
        s.update(stage='blocked',observed_task='new-failure')
        self.con.execute('UPDATE generic_calibration_workflows SET state=?',(json.dumps(s),));self.con.commit()
        self.assertEqual(self.migrate(),receipt)
        self.assertEqual(json.loads(self.con.execute('SELECT state FROM generic_calibration_workflows').fetchone()[0]),s)

    def test_insufficient_forged_or_unbound_seam_cannot_change_configuration(self):
        for mutate in (lambda p:p.update(candidate_manifest_sha256='0'*64),
                lambda p:p['paths']['tests/test_one.py'].pop('INDEX_HTML'),
                lambda p:p['product_sha256'].pop('app/index.html'),
                lambda p:p.update(execution_authorized=True),lambda p:p.update(operation='claimed_by_agent')):
            proof=copy.deepcopy(self.proof);mutate(proof)
            with self.assertRaises(ValueError):self.migrate(proof=proof)
        self.assertEqual(json.loads(self.con.execute('SELECT config FROM generic_calibration_workflows').fetchone()[0]),self.c)

    def test_active_foreign_or_unsealed_inputs_cannot_reopen_work(self):
        for override in (dict(task={**self.f.t,'status':'running'}),dict(task={**self.f.t,'agent_id':'author'}),
                dict(binding={**self.f.b,'status':'running'}),dict(barrier={**self.f.barrier,'stage':'released'})):
            with self.assertRaises(ValueError):self.migrate(**override)
        self.con.execute("UPDATE delivery_handoffs SET stage='done'");self.con.commit()
        with self.assertRaises(ValueError):self.migrate()

    def test_parent_save_failure_rolls_back_config_and_receipt(self):
        from unittest.mock import patch
        with patch.object(handoffs,'save',side_effect=ValueError('storage failed')):
            with self.assertRaises(ValueError):self.migrate()
        self.assertEqual(json.loads(self.con.execute('SELECT config FROM generic_calibration_workflows').fetchone()[0]),self.c)
        self.assertEqual(self.con.execute('SELECT count(*) FROM generic_calibration_capability_recoveries').fetchone()[0],0)

    def test_prior_protocol_ledger_is_preserved_not_reset(self):
        self.con.execute('CREATE TABLE generic_calibration_protocol_recoveries(issue_id TEXT,author_task TEXT,receipt TEXT)')
        old=json.dumps({'attempt_limit':1,'config_sha256':digest(self.c),'already_consumed':True})
        self.con.execute('INSERT INTO generic_calibration_protocol_recoveries VALUES(?,?,?)',('issue','author',old));self.con.commit()
        self.migrate()
        self.assertEqual(self.con.execute('SELECT receipt FROM generic_calibration_protocol_recoveries').fetchone()[0],old)

    def test_v2_dispatch_has_new_identity_and_lost_ack_only_observes(self):
        from broker import generic_calibration_workflow as workflow
        self.migrate();c=json.loads(self.con.execute('SELECT config FROM generic_calibration_workflows').fetchone()[0])
        events=[]
        class Effects:
            def verify(_,value):pass
            def reserve(_,value):return True
            def wake(_,value,note,marker,first):
                events.append((marker,first));raise TimeoutError('unknown acknowledgment')
        workflow.advance(self.con,c,Effects(),now=2);workflow.advance(self.con,c,Effects(),now=3)
        self.assertEqual(events[0][0],events[1][0]);self.assertEqual([v[1] for v in events],[True,False])
        old=digest(dict(config_sha256=digest(self.c),phase='bundle',protocol='generic-calibration-producer-v1'))
        self.assertNotEqual(events[0][0],old)
        state=json.loads(self.con.execute('SELECT state FROM generic_calibration_workflows').fetchone()[0])
        state['capability_recovery_sha256']='0'*64
        self.con.execute('UPDATE generic_calibration_workflows SET state=?',(json.dumps(state),));self.con.commit()
        workflow.advance(self.con,c,Effects(),now=4)
        self.assertEqual(len(events),2)
        self.assertEqual(json.loads(self.con.execute('SELECT state FROM generic_calibration_workflows').fetchone()[0])['stage'],'blocked')
