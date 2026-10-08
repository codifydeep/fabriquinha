import copy
import json
import unittest
import test_product_scope_task_binding as fixtures
from broker import product_scope_task_binding as binding, product_scope_worker as worker, handoff_runtime


class ProductScopeWorkerTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.ProductScopeTaskBindingTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.b,self.key,self.fx=self.f.b,self.f.key,self.f.fx
        self.bound=binding.bind(self.b,self.key,'new-author',self.fx)
        self.red=dict(issue_id='issue',task_id='red-author',volume='red-volume',red=dict(
            base_manifest_sha256=self.bound['original_base_manifest_sha256'],
            test_sha256=self.bound['frozen_test_sha256'],command=self.bound['contract']['test_command'],
            exit_code=1,test_count=5,manifest_sha256='1'*64,output_sha256='2'*64))
        self.review=dict(status='approved',source_task='red-author',candidate_volume='red-volume',
            manifest_sha256='1'*64,review_task='independent-review',read_contract='complete-lines-v2',
            decision=dict(action='approve_test_revision',manifest_sha256='1'*64,optional_files=[]))
        self.route=dict(enabled=True,test_first=True,author=self.bound['author'],test_first_files=list(self.bound['frozen_test_sha256']))
        with self.b.db() as con:
            con.executescript('CREATE TABLE test_first_red(issue_id TEXT,receipt TEXT);'
                'CREATE TABLE test_revision_trials(issue_id TEXT,state TEXT);CREATE TABLE delivery_routes(issue_id TEXT,config TEXT);')
            con.execute('INSERT INTO test_first_red VALUES (?,?)',('issue',json.dumps(self.red)))
            con.execute('INSERT INTO test_revision_trials VALUES (?,?)',('issue',json.dumps(self.review)))
            con.execute('INSERT INTO delivery_routes VALUES (?,?)',('issue',json.dumps(self.route)))
        prior=self.b.docker.side_effect
        self.b.docker.side_effect=lambda method,path,payload=None:(dict(Name='red-volume',Labels={
            'delivery-kit.owner':self.b.OWNER,'delivery-kit.test-first-task':'red-author'})
            if path=='/volumes/red-volume' else prior(method,path,payload))

    def test_selected_base_and_code_only_paths_preserve_original_red(self):
        result=worker.selection(self.b,'issue','new-author')
        self.assertEqual(result['base']['volume'],self.bound['volume'])
        self.assertIn('/workspace/app/db.py',result['editable_paths'])
        self.assertIn('/workspace/app/store.py',result['editable_paths'])
        self.assertFalse(any(path.startswith('/workspace/tests/') for path in result['editable_paths']))
        self.assertTrue(result['seed']['mount']['ReadOnly'])
        self.assertEqual(result['seed']['selection']['test_sha256'],self.bound['frozen_test_sha256'])
        self.assertFalse(result['provenance']['historical_red_recreated'])
        self.assertEqual(handoff_runtime.task_base(self.b,'issue','new-author')['volume'],self.bound['volume'])
        self.assertEqual(handoff_runtime.task_base(self.b,'issue','source'),self.b.issue_base('issue'))

    def test_unselected_tasks_never_inherit_revised_scope(self):
        self.assertIsNone(worker.selection(self.b,'issue','historical-task'))

    def test_red_hash_baseline_command_and_actual_failure_are_required(self):
        for mutation in ({'test_sha256':{}},{'base_manifest_sha256':'0'*64},{'exit_code':0},
                         {'exit_code':False},{'command':['echo','red']},{'test_count':0}):
            altered=copy.deepcopy(self.red);altered['red'].update(mutation)
            with self.b.db() as con:con.execute('UPDATE test_first_red SET receipt=?',(json.dumps(altered),))
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):worker.selection(self.b,'issue','new-author')

    def test_stale_incomplete_or_self_review_never_unlocks_product_code(self):
        for mutation in ({'status':'blocked'},{'source_task':'other'},{'candidate_volume':'other'},
                         {'manifest_sha256':'0'*64},{'review_task':'red-author'},
                         {'read_contract':'clipped'},{'decision':dict(action='reject_test_revision')}):
            with self.b.db() as con:con.execute('UPDATE test_revision_trials SET state=?',(json.dumps(dict(self.review,**mutation)),))
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):worker.selection(self.b,'issue','new-author')

    def test_scope_binding_does_not_create_legacy_latest_contract_binding(self):
        handoff_runtime.bind_contract(self.b,'new-author','issue')
        with self.b.db() as con:
            self.assertFalse(con.execute("SELECT 1 FROM sqlite_master WHERE name='task_contracts'").fetchone())
