import copy
import json
import sqlite3
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import test_remediation_runtime_guard as fixtures
from broker import remediation_test_review as adapter
from broker import test_revision_review as revision


class RemediationTestReviewTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.RemediationRuntimeGuardTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.b=self.f.b;self.b.LOCK=threading.RLock()
        old_db=self.b.db
        def db():
            con=old_db();con.row_factory=sqlite3.Row;return con
        self.b.db=db
        self.value={**self.f.value,'source_issue':'old','run_id':'recovery','plan_sha256':'9'*64}
        self.f.value=self.value
        from broker.technical_remediation_plan import digest
        self.f.state['contract_sha256']=digest(self.value)
        self.route={**self.f.route,'techlead':'lead','cto':'cto','minimum_calls':8,'enabled':False}
        self.old=dict(issue_id='old',task_id='historic',volume='frozen',scope='historic-scope',
            red=dict(evidence_version=2,exit_code=1,test_count=323,output_sha256='7'*64,
                manifest_sha256='d'*64,test_sha256={'tests/test_new.py':'e'*64},
                base_manifest_sha256='b'*64,baseline_test_sha256={'tests/test_existing.py':'f'*64},
                command=['python3','-m','unittest','discover','-s','.','-q'],test_image='immutable-image'))
        self.new=copy.deepcopy(self.old)
        self.new.update(issue_id='r1',task_id='new-author-task',volume='candidate',scope='new-scope')
        self.new['red'].update(manifest_sha256='8'*64,test_sha256={'tests/test_new.py':'6'*64})
        self.f.save(value=self.value,state=self.f.state,route=self.route)
        with self.b.db() as con:
            from broker import handoffs
            handoffs.initialize(con)
            con.execute('ALTER TABLE test_first_red ADD COLUMN receipt TEXT')
            con.execute('INSERT INTO test_first_red VALUES (?,?)',('old',json.dumps(self.old)))
            con.execute('INSERT INTO delivery_routes VALUES (?,?)',('old',json.dumps(self.route)))
        self.b.docker=lambda method,path:dict(Labels={'delivery-kit.owner':'owner',
            'delivery-kit.test-first-task':'historic' if 'frozen' in path else 'new-author-task'})

    def capture(self,red=None):
        with self.b.db() as con:
            con.execute('INSERT OR REPLACE INTO test_first_red VALUES (?,?)',('r1',json.dumps(red or self.new)))

    def test_contract_binds_previous_delivery_without_recursive_child_or_first_review(self):
        cfg=adapter.install(self.b,'r1')
        self.assertEqual(cfg['old_red'],self.old)
        self.assertEqual(cfg['reviewer'],'lead')
        self.assertEqual(cfg['remediation_run_id'],'recovery')
        self.assertFalse(cfg.get('initial_review',False))
        self.assertNotIn('parent_issue',cfg)
        self.assertEqual(adapter.install(self.b,'r1'),cfg)
        with self.b.db() as con:
            self.assertIsNone(con.execute('SELECT parent_issue FROM test_revision_trials WHERE issue_id=?',('r1',)).fetchone()[0])
            self.assertEqual(con.execute('SELECT count(*) FROM test_first_red WHERE issue_id=?',('r1',)).fetchone()[0],0)

    def test_amendment_uses_foreign_red_identity_without_manufacturing_local_receipt(self):
        from broker import remediation_red_reference as references
        old={**self.old,'issue_id':'original-r1'}
        value={**self.value,'amendment':dict(seed_red=old)}
        with self.b.db() as con:con.execute('DELETE FROM test_first_red WHERE issue_id=?',('old',))
        with patch.object(adapter.guard,'qualified',return_value=value),patch.object(references,'qualified',return_value=dict(red=old,origin_issue='original-r1')):
            cfg=adapter.config(self.b,'r1')
        self.assertEqual(cfg['old_red']['issue_id'],'original-r1')
        with self.b.db() as con:
            self.assertIsNone(con.execute('SELECT receipt FROM test_first_red WHERE issue_id=?',('old',)).fetchone())
        with patch.object(adapter.guard,'qualified',return_value=value),patch.object(references,'qualified',return_value=dict(red={**old,'task_id':'stale'},origin_issue='original-r1')):
            with self.assertRaises(ValueError):adapter.config(self.b,'r1')

    def test_stale_previous_receipt_and_self_review_cannot_install(self):
        for bad in ({**self.old,'volume':'wrong'}, {**self.old,'task_id':'wrong'}):
            with self.b.db() as con:con.execute('UPDATE test_first_red SET receipt=? WHERE issue_id=?',(json.dumps(bad),'old'))
            with self.assertRaises(ValueError):adapter.install(self.b,'r1')
        with self.b.db() as con:con.execute('UPDATE test_first_red SET receipt=? WHERE issue_id=?',(json.dumps(self.old),'old'))
        self.f.save(route={**self.route,'techlead':'author'})
        with self.assertRaises(ValueError):adapter.install(self.b,'r1')

    def test_full_real_new_red_required_not_historical_or_relabelled_receipt(self):
        adapter.install(self.b,'r1')
        effects=SimpleNamespace(test_review_report=lambda *args:None)
        with self.assertRaises(ValueError):adapter.verify(self.b,'r1',self.route,self.new,effects)
        for mutate in (lambda r:r.update(task_id='historic'),lambda r:r['red'].update(test_sha256=self.old['red']['test_sha256']),
                       lambda r:r['red'].update(command=['python3','test_one.py']),
                       lambda r:r['red'].update(baseline_test_sha256={}),lambda r:r['red'].update(test_count=322),
                       lambda r:r['red'].update(evidence_version=1),lambda r:r['red'].update(exit_code=0)):
            bad=copy.deepcopy(self.new);mutate(bad)
            with self.b.db() as con:con.execute('DELETE FROM test_first_red WHERE issue_id=?',('r1',))
            self.capture(bad)
            with self.assertRaises(ValueError):adapter.verify(self.b,'r1',self.route,bad,effects)

    def test_verification_does_not_grant_product_or_accept_missing_comparison_operation(self):
        adapter.install(self.b,'r1');self.capture()
        with self.assertRaises(ValueError):adapter.verify(self.b,'r1',self.route,self.new,SimpleNamespace())
        adapter.verify(self.b,'r1',self.route,self.new,SimpleNamespace(test_review_report=lambda *args:None))
        from broker.remediation_runtime_guard import phase
        self.assertEqual(phase(self.b,'r1'),'tests_only')

    def test_reconcile_dispatches_both_trees_and_controller_comparison_not_first_submission(self):
        cfg=adapter.install(self.b,'r1');self.capture()
        summary=self.summary()
        captured=[]
        effects=SimpleNamespace(remaining_calls=lambda:64,test_review_report=lambda issue,red,prior:summary,
            ensure_wakeup=lambda *args,**kwargs:captured.append(args[-1]) or dict(id='wake'))
        self.assertFalse(revision.reconcile(self.b,self.route,[],effects,self.new))
        self.assertIn('/evidence/candidate/tests/test_new.py',captured[0])
        self.assertIn('/evidence/previous/tests/test_new.py',captured[0])
        self.assertNotIn('Approval permits implementation only',captured[0])
        with self.b.db() as con:
            state=json.loads(con.execute('SELECT state FROM test_revision_trials WHERE issue_id=?',('r1',)).fetchone()[0])
            self.assertEqual(state['previous_volume'],'frozen')
            self.assertEqual(state['comparison']['previous_manifest'],'d'*64)

    def test_modified_installed_review_contract_rejected_before_wakeup(self):
        cfg=adapter.install(self.b,'r1');self.capture()
        with self.b.db() as con:
            con.execute('UPDATE test_revision_trials SET config=?',(json.dumps({**cfg,'initial_review':True}),))
        with self.assertRaises(ValueError):adapter.install(self.b,'r1')
        with self.assertRaises(ValueError):adapter.verify(self.b,'r1',self.route,self.new,
            SimpleNamespace(test_review_report=lambda *args:None))

    def test_approval_with_missing_or_stale_snapshot_and_reads_is_not_reused(self):
        adapter.install(self.b,'r1');self.capture()
        state=dict(status='approved',evidence_policy=1,read_contract='complete-lines-v2',
            comparison=self.summary(),
            source_task='new-author-task',candidate_volume='candidate',previous_volume='frozen',
            manifest_sha256='8'*64,review_task='review',decision=dict(action='approve_test_revision',manifest_sha256='8'*64))
        effects=SimpleNamespace(test_review_report=lambda *args:None,read_evidence=lambda task:{})
        for change in (dict(manifest_sha256='0'*64),dict(previous_volume='wrong'),dict(review_task='new-author-task'),dict()):
            with self.b.db() as con:
                con.execute('UPDATE test_revision_trials SET state=?',(json.dumps({**state,**change}),))
            with self.assertRaises(ValueError):adapter.verify(self.b,'r1',self.route,self.new,effects)

    def test_approval_cannot_hide_removed_methods_or_assertions(self):
        approving=dict(action='approve_test_revision',findings=[])
        for file in (dict(removed_methods=['test_old'],removed_assertion_ast={}),
                     dict(removed_methods=[],removed_assertion_ast={'test_old':{'assert':1}})):
            with self.assertRaises(ValueError):adapter.preserve_coverage(approving,dict(files={'tests/test_new.py':file}))
        adapter.preserve_coverage(approving,dict(files={'tests/test_new.py':dict(removed_methods=[],removed_assertion_ast={})}))
        adapter.preserve_coverage(dict(action='reject_test_revision'),dict(files={'tests/test_new.py':file}))

    def summary(self):
        return dict(candidate_manifest='8'*64,previous_manifest='d'*64,files={'tests/test_new.py':dict(
            candidate_sha256='6'*64,previous_sha256='e'*64,removed_methods=[],removed_assertion_ast={},
            previous_methods=['Cases.test_old'],candidate_methods=['Cases.test_old'],
            previous_assertions=1,candidate_assertions=1,added_methods=[])})

    def test_partial_or_wrong_hash_comparison_is_rejected(self):
        cfg=adapter.install(self.b,'r1')
        for bad in (dict(candidate_manifest='8'*64,previous_manifest='d'*64,files={}),
                    {**self.summary(),'previous_manifest':'0'*64}):
            with self.assertRaises(ValueError):adapter.validate_comparison(cfg,self.new,bad)
        bad=self.summary();bad['files']['tests/test_new.py']['previous_sha256']='0'*64
        with self.assertRaises(ValueError):adapter.validate_comparison(cfg,self.new,bad)

    def test_approved_r1_records_exact_gate_without_product_dispatch_or_depth_reset(self):
        adapter.install(self.b,'r1');self.capture()
        state=dict(status='approved',evidence_policy=1,read_contract='complete-lines-v2',comparison=self.summary(),
            source_task='new-author-task',candidate_volume='candidate',previous_volume='frozen',
            manifest_sha256='8'*64,review_task='review',decision=dict(action='approve_test_revision',manifest_sha256='8'*64))
        with self.b.db() as con:con.execute('UPDATE test_revision_trials SET state=?',(json.dumps(state),))
        effects=SimpleNamespace(test_review_report=lambda *args:None,read_evidence=lambda task:{
            '/evidence/'+tree+'/tests/test_new.py':dict(lines=700,total_lines=700) for tree in ('candidate','previous')})
        with patch.object(revision,'validate_evidence'):
            self.assertTrue(adapter.record_gate(self.b,self.route,self.new,effects))
            self.assertTrue(adapter.record_gate(self.b,self.route,self.new,effects))
        with self.b.db() as con:
            state=json.loads(con.execute('SELECT state FROM remediation_executions').fetchone()[0])
            route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',('r1',)).fetchone()[0])
        self.assertEqual(state['r1_gate']['red'],self.new)
        self.assertFalse(state['r1_gate']['product_execution_authorized'])
        self.assertFalse(state['r1_gate']['release_homologated'])
        self.assertFalse(route['enabled'])
        self.assertEqual(state['steps']['R1']['stage'],'approved')


if __name__=='__main__':unittest.main()
