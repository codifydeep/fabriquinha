import copy
import json
import sqlite3
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import test_remediation_test_review as fixtures
from broker import remediation_red_reference as references
from broker.technical_remediation_plan import digest


class RemediationRedReferenceTests(unittest.TestCase):
    def setUp(self):
        f=fixtures.RemediationTestReviewTests();f.setUp();self.addCleanup(f.doCleanups);self.f=f;self.b=f.b
        self.value={**f.value,'root_issue':'root','criteria':{'A01':'full criterion'},'steps':[
            {**f.value['steps'][0],'criteria':['A01']},
            dict(id='R2',edit_scope='product_only',depends_on=['R1'],criteria=['A01'],owner='author',editable_files=['app.js'])]}
        gate=dict(operation='immutable_remediation_r1_gate_v1',run_id=self.value['run_id'],
            execution_contract_sha256=digest(self.value),red=f.new,review_task='review',
            review_decision=dict(action='approve_test_revision',manifest_sha256='8'*64),
            product_execution_authorized=False,release_homologated=False)
        self.state={**f.f.state,'contract_sha256':digest(self.value),'r1_gate':gate,
            'steps':{'R1':dict(stage='approved',issue_id='r1',manifest_sha256='8'*64,review_task='review')}}
        f.f.save(value=self.value,state=self.state)
        self.route=dict(issue_id='r2',author='author',techlead='lead',cto='cto',reviewer='product-reviewer',
                        contract_sha256='c'*64,enabled=False)
        self.b.issue_base=lambda issue:{**self.value['base'],'issue_id':issue,'volume':'delivery-kit-port2-base-'+issue}
        f.capture()
        with self.b.db() as c:
            from broker import test_revision_review
            test_revision_review.initialize(c)
            policy=dict(reviewer='lead',old_red=f.old,remediation_execution_sha256=digest(self.value))
            approved=dict(status='approved',review_task='review',decision=gate['review_decision'],
                manifest_sha256='8'*64,source_task='new-author-task',candidate_volume='candidate',
                read_contract='complete-lines-v2',previous_volume='frozen')
            c.execute('INSERT INTO test_revision_trials VALUES (?,?,?,?)',('r1',None,json.dumps(policy),json.dumps(approved)))
            r1={**f.route,'reviewer':'product-reviewer'}
            c.execute('UPDATE delivery_routes SET config=? WHERE issue_id=?',(json.dumps(r1),'r1'))
            c.execute('INSERT INTO delivery_routes VALUES (?,?)',('r2',json.dumps(self.route)))
            c.execute('CREATE TABLE issue_editables(issue_id TEXT,path TEXT)')
            c.execute('INSERT INTO issue_editables VALUES (?,?)',('r2','/workspace/app.js'))
            c.execute('CREATE TABLE native_bindings(task_id TEXT,issue_id TEXT,scope TEXT,agent_id TEXT,request_id TEXT)')
            c.execute('CREATE TABLE grants(request_id TEXT,mode TEXT)')
            c.execute('CREATE TABLE leases(request_id TEXT,status TEXT)')

    def register(self):
        with patch.object(references.review,'verify'):
            return references.register(self.b,'r2','source',SimpleNamespace())

    def task(self,author='author',mode='implementation',status='closed'):
        with self.b.db() as c:
            c.execute('INSERT INTO native_bindings VALUES (?,?,?,?,?)',('product-task','r2','different-scope',author,'request'))
            c.execute('INSERT INTO grants VALUES (?,?)',('request',mode))
            c.execute('INSERT INTO leases VALUES (?,?)',('request',status))
            c.execute('UPDATE delivery_routes SET config=? WHERE issue_id=?',(json.dumps({**self.route,'enabled':True}),'r2'))

    def test_durable_reference_keeps_origin_and_does_not_insert_fake_red(self):
        receipt=self.register()
        self.assertEqual(receipt['red'],self.f.new)
        self.assertEqual(receipt['origin_issue'],'r1')
        self.assertFalse(receipt['execution_authorized'])
        self.assertEqual(self.register(),receipt)
        with self.b.db() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM test_first_red WHERE issue_id=?',('r2',)).fetchone()[0],0)
        self.assertEqual(references.phase(self.b,'r2'),'implement_after_red')
        seed=references.seed_source(self.b,'r2')
        self.assertEqual(seed['mount']['Source'],'candidate')
        self.assertTrue(seed['mount']['ReadOnly'])

    def test_r2_permission_contains_only_product_paths_and_original_baseline(self):
        with self.b.db() as c:c.execute('INSERT INTO issue_editables VALUES (?,?)',('r2','/workspace/tests/test_new.py'))
        with self.assertRaises(ValueError):self.register()

    def test_task_red_is_reference_not_same_scope_override_and_requires_closed_author_lease(self):
        self.register();self.task()
        red=references.task_red(self.b,'product-task')
        self.assertEqual(red,self.f.new)
        self.assertEqual(red['issue_id'],'r1')
        self.assertNotEqual(red['scope'],'different-scope')
        with self.b.db() as c:c.execute("UPDATE grants SET mode='planning'")
        with self.assertRaises(ValueError):references.task_red(self.b,'product-task')

    def test_stale_gate_route_seed_or_baseline_cannot_reuse_reference(self):
        self.register()
        bad=copy.deepcopy(self.state);bad['r1_gate']['review_decision']['manifest_sha256']='0'*64
        self.f.f.save(state=bad)
        with self.assertRaises(ValueError):references.phase(self.b,'r2')
        self.f.f.save(state=self.state)
        self.b.docker=lambda *args:dict(Labels={'delivery-kit.owner':'foreign'})
        with self.assertRaises(ValueError):references.seed_source(self.b,'r2')

    def test_unrelated_legacy_issues_have_no_reference(self):
        self.assertIsNone(references.phase(self.b,'unrelated'))
        self.assertIsNone(references.seed_source(self.b,'unrelated'))

    def test_paused_route_allows_only_diagnostic_red_reference_not_delivery(self):
        self.register();self.task()
        with self.b.db() as c:
            c.execute('UPDATE delivery_routes SET config=? WHERE issue_id=?',(json.dumps(self.route),'r2'))
        with self.assertRaises(ValueError):references.task_red(self.b,'product-task')
        self.assertEqual(references.task_red(self.b,'product-task',diagnostic=True),self.f.new)
        with self.b.db() as c:c.execute("UPDATE grants SET mode='planning'")
        with self.assertRaises(ValueError):references.task_red(self.b,'product-task',diagnostic=True)
        self.assertIsNone(references.task_red(self.b,'unknown-task'))

    def test_unrelated_workers_do_not_starve_paused_reference_registration(self):
        with self.b.db() as con:
            con.execute('INSERT INTO leases VALUES (?,?)',('other','running'))
            con.execute('INSERT INTO native_bindings VALUES (?,?,?,?,?)',('other-task','other-issue','other-scope','other-agent','other'))
        self.assertFalse(self.register()['execution_authorized'])

    def test_dependency_worker_prevents_reference_registration(self):
        with self.b.db() as con:
            con.execute('INSERT INTO leases VALUES (?,?)',('dependency','closing'))
            con.execute('INSERT INTO native_bindings VALUES (?,?,?,?,?)',('review','r1','scope','lead','dependency'))
        with self.assertRaises(ValueError):self.register()

    def test_registration_cannot_rebind_an_issue_to_another_execution(self):
        self.register()
        with self.b.db() as c:
            c.execute('UPDATE remediation_red_references SET source_task=?',('wrong',))
        with self.assertRaises(ValueError):references.phase(self.b,'r2')

    def test_revoked_independent_review_cannot_continue_r2(self):
        self.register()
        with self.b.db() as c:
            state=json.loads(c.execute('SELECT state FROM test_revision_trials WHERE issue_id=?',('r1',)).fetchone()[0])
            c.execute('UPDATE test_revision_trials SET state=?',(json.dumps({**state,'status':'blocked'}),))
        with self.assertRaises(ValueError):references.phase(self.b,'r2')

    def test_real_effects_freeze_green_and_tdd_preserve_foreign_origin(self):
        from broker.handoff_runtime import Effects,initialize
        self.register();self.task()
        with self.b.db() as c:initialize(c)
        events=[]
        self.b.snapshot_submission=lambda payload:events.append('snapshot') or dict(volume='final-snapshot')
        self.b.validate_frozen_delivery=lambda volume,task:events.append('full-green') or dict(manifest_sha256='9'*64,tests=323)
        self.b.verify_test_first_green=lambda volume,task,red:events.append(('verify-frozen-tests',red['issue_id'])) or True
        effects=Effects(self.b,{})
        self.assertEqual(effects.test_first_red('product-task'),self.f.new)
        snapshot=effects.freeze('product-task');result=effects.validate(snapshot,'product-task')
        self.assertEqual(result['tdd']['test_task'],'new-author-task')
        self.assertEqual(result['tdd']['red_origin_issue'],'r1')
        self.assertIn(('verify-frozen-tests','r1'),events)
        self.assertEqual(events[0],'snapshot')
        with self.b.db() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM test_first_red WHERE issue_id=?',('r2',)).fetchone()[0],0)

    def test_review_or_running_execution_cannot_consume_product_red(self):
        self.register();self.task(status='running')
        with self.assertRaises(ValueError):references.task_red(self.b,'product-task')


if __name__=='__main__':unittest.main()
