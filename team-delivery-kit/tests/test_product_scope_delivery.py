import copy
import json
import unittest
from unittest.mock import Mock,patch
import test_product_scope_green as fixtures
from broker import product_scope_delivery as gate, handoff_runtime
from portable_scope_gate import qualify,QUERY
import portable_delivery as driver
import test_portable_remediation_gate as driverfixtures


class ProductScopeDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.ProductScopeGreenTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.b,self.bound=self.f.b,self.f.bound
        self.delivery=dict(source_task='new-author',review_task='code-review',author=self.bound['author'],reviewer='reviewer',
                           manifest_sha256=self.f.result['manifest_sha256'],volume='candidate')
        with self.b.db() as con:
            con.executescript('CREATE TABLE delivery_tdd(task_id TEXT PRIMARY KEY,receipt TEXT);'
                'CREATE TABLE reviews(review_task_id TEXT,source_task_id TEXT,reviewer_agent_id TEXT,manifest_sha256 TEXT,status TEXT);'
                'CREATE TABLE snapshots(task_id TEXT,volume TEXT,status TEXT);')
            con.execute('INSERT INTO reviews VALUES (?,?,?,?,?)',('code-review','new-author','reviewer',self.delivery['manifest_sha256'],'approved'))
            con.execute('INSERT INTO snapshots VALUES (?,?,?)',('new-author','candidate','complete'))
        self.b.validate_frozen_delivery=Mock(return_value=self.f.result)
        self.b.verify_test_first_green=Mock(return_value=True)
        self.tdd=handoff_runtime.Effects(self.b,{}).validate(dict(volume='candidate'),'new-author')['tdd']
        prior=self.b.docker.side_effect
        self.b.docker.side_effect=lambda method,path,payload=None:(dict(Name='candidate',Labels={
            'delivery-kit.owner':self.b.OWNER,'delivery-kit.source-task':'new-author'})
            if path=='/volumes/candidate' else prior(method,path,payload))
        self.fx=Mock()
        self.fx.task.side_effect=lambda task,actor:dict(id=task,agent_id=actor,issue_id='issue',status='completed')
        from broker import product_scope_worker
        configuration=product_scope_worker.selection(self.b,'issue','new-author')
        paths={'/delivery/'+p.removeprefix('/workspace/') for p in configuration['editable_paths']}
        paths.update('/delivery/'+p for p in self.bound['frozen_test_sha256'])
        self.fx.delivery_reads.return_value={p:dict(lines=10,total_lines=10) for p in paths}
        self.original=self.f.f.f.f.f.original

    def test_exact_scope_delivery_preserves_independent_review_and_all_other_gates(self):
        proof=gate.qualified(self.b,'issue',self.delivery,self.fx)
        self.assertEqual(proof['contract'],self.bound['contract'])
        self.assertFalse(proof['release_homologated'])
        context=dict(issue_id='issue',base_sha=self.bound['base_sha'],contract_sha256=proof['original_contract_sha256'])
        command=Mock(return_value=json.dumps(proof))
        self.assertEqual(qualify(command,'delivery-kit-test',context,self.delivery,self.original),proof)
        self.assertEqual(command.call_args.args[5],QUERY)
        compile(QUERY,'<fixed scope query>','exec')

    def test_stale_or_self_review_and_incomplete_native_tasks_cannot_publish(self):
        with self.b.db() as con:con.execute("UPDATE reviews SET status='changes_requested'")
        with self.assertRaises(ValueError):gate.qualified(self.b,'issue',self.delivery,self.fx)
        with self.b.db() as con:con.execute("UPDATE reviews SET status='approved'")
        self.fx.task.side_effect=lambda task,actor:dict(id=task,agent_id=actor,issue_id='issue',status='failed')
        with self.assertRaises(ValueError):gate.qualified(self.b,'issue',self.delivery,self.fx)

    def test_tests_only_approval_or_partial_code_inspection_cannot_publish(self):
        complete=copy.deepcopy(self.fx.delivery_reads.return_value)
        self.fx.delivery_reads.return_value={}
        with self.assertRaisesRegex(ValueError,'complete independent scoped code'):
            gate.qualified(self.b,'issue',self.delivery,self.fx)
        for path in complete:
            for incomplete in ({},{'lines':9,'total_lines':10},{'lines':0,'total_lines':0},{'lines':True,'total_lines':True}):
                self.fx.delivery_reads.return_value=dict(complete,**{path:incomplete})
                with self.subTest(path=path,incomplete=incomplete),self.assertRaises(ValueError):
                    gate.qualified(self.b,'issue',self.delivery,self.fx)

    def test_tdd_scope_bridge_cannot_be_swapped_or_weakened_before_publication(self):
        for mutation in ({'delivery_manifest_sha256':'0'*64},{'delivery_approval':True},{'historical_red_recreated':True},
                         {'revised_contract_sha256':'0'*64},{'baseline_test_sha256':{}},{'frozen_test_sha256':{}}):
            tdd=copy.deepcopy(self.tdd);tdd['scope_transition'].update(mutation)
            with self.b.db() as con:con.execute('UPDATE delivery_tdd SET receipt=?',(json.dumps(tdd),))
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):gate.qualified(self.b,'issue',self.delivery,self.fx)

    def test_host_refuses_missing_previous_proof_or_changed_contract_and_acceptance(self):
        proof=gate.qualified(self.b,'issue',self.delivery,self.fx)
        context=dict(issue_id='issue',base_sha=proof['base_sha'],contract_sha256=proof['original_contract_sha256'])
        with self.assertRaises(ValueError):qualify(Mock(return_value='null'),'delivery-kit-test',context,self.delivery,self.original,previous=proof)
        for mutation in ({'release_homologated':True},{'scope_tdd_sha256':'invalid'},{'delivery':{}},{'base_sha':'0'*40}):
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):
                qualify(Mock(return_value=json.dumps(dict(proof,**mutation))),'delivery-kit-test',context,self.delivery,self.original)
        altered=copy.deepcopy(proof)
        altered['contract']['qa_cases'][0]['expected_json']={'status':'different-acceptance'}
        from broker.product_scope_revision import digest
        altered['effective_contract_sha256']=digest(altered['contract'])
        with self.assertRaises(ValueError):
            qualify(Mock(return_value=json.dumps(altered)),'delivery-kit-test',context,self.delivery,self.original)

    def driver_case(self,qualification=None):
        f=driverfixtures.PortableRemediationGateTests();f.setUp();self.addCleanup(f.doCleanups)
        context,mocks=f.driver_case()
        proof=gate.qualified(self.b,'issue',self.delivery,self.fx)
        context.update(issue_id='issue',base_sha=proof['base_sha'],contract_sha256=proof['original_contract_sha256'],durable_handoffs=True)
        mocks['approved'].return_value=self.delivery;mocks['qualify_remediation_delivery'].return_value=None
        command=patch.object(driver,'command',return_value='null');command.start();self.addCleanup(command.stop)
        guard=patch.object(driver,'qualify_scope_delivery',return_value=proof,side_effect=qualification)
        mocks['scope']=guard.start();self.addCleanup(guard.stop)
        return context,mocks,proof

    def test_driver_uses_revised_contract_and_rechecks_exact_proof_before_merge_and_deploy(self):
        context,mocks,proof=self.driver_case()
        receipt=driver.reconcile(context,self.original)
        self.assertEqual(receipt['scope_delivery'],proof)
        self.assertEqual(mocks['snapshot_files'].call_args.args[2],proof['contract'])
        self.assertEqual(mocks['scope'].call_count,3)
        self.assertEqual(mocks['approved'].call_count,3)
        for call in mocks['scope'].call_args_list[1:]:self.assertEqual(call.kwargs['previous'],proof)

    def test_revoked_scope_proof_prevents_merge(self):
        proof=gate.qualified(self.b,'issue',self.delivery,self.fx)
        context,mocks,_=self.driver_case([proof,ValueError('revoked')])
        with self.assertRaises(ValueError):driver.reconcile(context,self.original)
        mocks['ensure_merge'].assert_not_called();mocks['ensure_deployed'].assert_not_called()

    def test_revoked_scope_after_merge_prevents_deployment(self):
        proof=gate.qualified(self.b,'issue',self.delivery,self.fx)
        context,mocks,_=self.driver_case([proof,proof,ValueError('revoked')])
        with self.assertRaises(ValueError):driver.reconcile(context,self.original)
        mocks['ensure_merge'].assert_called_once();mocks['ensure_deployed'].assert_not_called()

    def test_persisted_scope_proof_cannot_be_bypassed_by_disabling_handoffs(self):
        context,mocks,_=self.driver_case()
        driver.reconcile(context,self.original)
        mocks['ensure_merge'].reset_mock();mocks['ensure_deployed'].reset_mock()
        with self.assertRaises(ValueError):driver.reconcile(dict(context,durable_handoffs=False),self.original)
        mocks['ensure_merge'].assert_not_called();mocks['ensure_deployed'].assert_not_called()
