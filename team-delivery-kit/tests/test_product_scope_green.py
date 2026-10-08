import copy
import json
import unittest
from unittest.mock import Mock
import test_product_scope_worker as fixtures
from broker import product_scope_worker as worker, handoff_runtime


class ProductScopeGreenTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.ProductScopeWorkerTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.b,self.bound=self.f.b,self.f.bound
        self.red=copy.deepcopy(self.f.red)
        self.red['scope']='original-workspace-scope'
        self.red['red']['baseline_test_sha256']={'tests/test_old.py':'3'*64}
        self.result=dict(manifest_sha256='4'*64,baseline_tests_intact=True,portable=True,tests=5,
            checkpoint_evidence=dict(base_manifest_sha256=self.bound['manifest_sha256'],
                baseline_test_sha256=self.red['red']['baseline_test_sha256'],
                new_test_sha256=self.bound['frozen_test_sha256']))
        with self.b.db() as con:
            con.execute('UPDATE test_first_red SET receipt=?',(json.dumps(self.red),))
            con.execute('CREATE TABLE native_bindings(task_id TEXT,issue_id TEXT,agent_id TEXT,scope TEXT)')
            con.execute('INSERT INTO native_bindings VALUES (?,?,?,?)',('new-author','issue',self.bound['author'],
                        'workspace:'+self.bound['author']+':implementation:new-author'))

    def test_scope_bridge_returns_the_original_red_without_rewriting_its_origin(self):
        self.assertEqual(worker.red_reference(self.b,'new-author'),self.red)
        self.assertEqual(worker.red_reference(self.b,'new-author')['scope'],'original-workspace-scope')
        self.assertIsNone(worker.red_reference(self.b,'historical-task'))
        fx=handoff_runtime.Effects(self.b,{})
        self.assertEqual(fx.test_first_red('new-author'),self.red)

    def test_green_receipt_requires_both_contract_bases_and_is_not_delivery_approval(self):
        proof=worker.green_transition(self.b,'new-author',self.result,self.red,tests_unchanged=True)
        self.assertEqual(proof['original_base_manifest_sha256'],self.bound['original_base_manifest_sha256'])
        self.assertEqual(proof['revised_base_manifest_sha256'],self.bound['manifest_sha256'])
        self.assertEqual(proof['red_task'],self.red['task_id'])
        self.assertFalse(proof['historical_red_recreated']);self.assertFalse(proof['delivery_approval'])

    def test_scope_mismatch_stale_hash_missing_baseline_and_partial_suite_are_rejected(self):
        for mutation in ({'tests':4},{'tests':True},{'baseline_tests_intact':False},{'portable':False},
                         {'manifest_sha256':'not-a-hash'},{'checkpoint_evidence':{}},
                         {'checkpoint_evidence':dict(self.result['checkpoint_evidence'],base_manifest_sha256='0'*64)},
                         {'checkpoint_evidence':dict(self.result['checkpoint_evidence'],baseline_test_sha256={})},
                         {'checkpoint_evidence':dict(self.result['checkpoint_evidence'],new_test_sha256={})}):
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):
                worker.green_transition(self.b,'new-author',dict(self.result,**mutation),self.red,tests_unchanged=True)
        for verification in (False,1,None):
            with self.subTest(verification=verification),self.assertRaises(ValueError):
                worker.green_transition(self.b,'new-author',self.result,self.red,tests_unchanged=verification)

    def test_native_author_identity_and_original_red_bytes_cannot_be_substituted(self):
        with self.assertRaises(ValueError):worker.green_transition(self.b,'new-author',self.result,dict(self.red,scope='rewritten'),tests_unchanged=True)
        with self.b.db() as con:con.execute('UPDATE native_bindings SET agent_id=?',('cto',))
        with self.assertRaises(ValueError):worker.red_reference(self.b,'new-author')

    def test_controller_validation_preserves_red_and_persists_bridge_only_after_green(self):
        with self.b.db() as con:con.execute('CREATE TABLE delivery_tdd(task_id TEXT PRIMARY KEY,receipt TEXT)')
        self.b.validate_frozen_delivery=Mock(return_value=self.result)
        self.b.verify_test_first_green=Mock(return_value=True)
        fx=handoff_runtime.Effects(self.b,{})
        result=fx.validate(dict(volume='candidate'), 'new-author')
        self.assertEqual(result['tdd']['red'],self.red['red'])
        self.assertFalse(result['tdd']['scope_transition']['delivery_approval'])
        self.b.verify_test_first_green.assert_called_once_with('candidate','new-author',self.red)
        with self.b.db() as con:
            stored=json.loads(con.execute('SELECT receipt FROM delivery_tdd WHERE task_id=?',('new-author',)).fetchone()[0])
        self.assertEqual(stored,result['tdd'])
        self.b.validate_frozen_delivery.return_value=dict(self.result,manifest_sha256='5'*64)
        with self.assertRaises(ValueError):fx.validate(dict(volume='other-candidate'),'new-author')
