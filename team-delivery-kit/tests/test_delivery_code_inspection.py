import contextlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from broker import delivery_code_inspection as policy


class DeliveryCodeInspectionTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.path=Path(temp.name)/'state.sqlite';self.b=SimpleNamespace(db=self.db)
        with self.db() as c:
            c.executescript('CREATE TABLE delivery_routes(issue_id TEXT,config TEXT);'
                'CREATE TABLE native_bindings(request_id TEXT,issue_id TEXT,agent_id TEXT,task_id TEXT);'
                'CREATE TABLE grants(request_id TEXT,mode TEXT);'
                'CREATE TABLE review_assignments(review_agent_id TEXT,source_task_id TEXT,volume TEXT);'
                'CREATE TABLE snapshots(task_id TEXT,volume TEXT,status TEXT);'
                'CREATE TABLE delivery_tdd(task_id TEXT,receipt TEXT);'
                'CREATE TABLE issue_editables(issue_id TEXT,path TEXT);')
            route=dict(enabled=True,test_first=True,author='author',reviewer='reviewer',test_first_files=['tests/test_new.py'])
            c.execute('INSERT INTO delivery_routes VALUES (?,?)',('issue',json.dumps(route)))
            c.executemany('INSERT INTO native_bindings VALUES (?,?,?,?)',
                [('author-request','issue','author','source'),('review-request','issue','reviewer','review')])
            c.execute('INSERT INTO grants VALUES (?,?)',('review-request','review'))
            c.execute('INSERT INTO review_assignments VALUES (?,?,?)',('reviewer','source','frozen'))
            c.execute('INSERT INTO snapshots VALUES (?,?,?)',('source','frozen','complete'))
            c.execute('INSERT INTO delivery_tdd VALUES (?,?)',('source',json.dumps(dict(mode='controller_test_first',
                implementation_task='source',test_task='red',red={'test_sha256':{'tests/test_new.py':'a'*64}}))))
            c.executemany('INSERT INTO issue_editables VALUES (?,?)',
                         [('issue','/workspace/app.js'),('issue','/workspace/tests/test_new.py')])
        self.lookup=patch.object(policy.binding,'lookup',return_value=None).start();self.addCleanup(patch.stopall)
        self.fx=Mock();self.fx.task.side_effect=lambda identity,agent:dict(id=identity,agent_id=agent,
            issue_id='issue',status='completed' if identity=='source' else 'running')

    @contextlib.contextmanager
    def db(self):
        c=sqlite3.connect(self.path)
        try:
            with c:yield c
        finally:c.close()

    def test_registered_code_and_frozen_tests_bind_exact_independent_tasks(self):
        self.assertEqual(policy.read_contract(self.b,'review-request',self.fx),
                         ['/delivery/app.js','/delivery/tests/test_new.py'])
        self.assertEqual(self.fx.task.call_count,2)
        self.assertIsNone(policy.read_contract(self.b,'unknown',self.fx))

    def test_scope_deliveries_keep_dedicated_gate_and_planning_cannot_get_review(self):
        self.lookup.return_value={'bound':'scope'}
        self.assertIsNone(policy.read_contract(self.b,'review-request',self.fx))
        self.lookup.return_value=None
        with self.db() as c:c.execute("UPDATE grants SET mode='planning'")
        self.assertIsNone(policy.read_contract(self.b,'review-request',self.fx))
        self.fx.task.assert_not_called()

    def test_incomplete_source_wrong_actor_or_snapshot_cannot_supply_contract(self):
        self.fx.task.side_effect=lambda identity,agent:dict(id=identity,agent_id=agent,issue_id='issue',status='running')
        with self.assertRaises(ValueError):policy.read_contract(self.b,'review-request',self.fx)
        with self.db() as c:c.execute("UPDATE snapshots SET volume='other'")
        with self.assertRaises(ValueError):policy.read_contract(self.b,'review-request',self.fx)

    def test_missing_or_recreated_red_and_wrong_source_binding_are_rejected(self):
        with self.db() as c:c.execute('DELETE FROM delivery_tdd')
        with self.assertRaises(ValueError):policy.paths(self.b,'issue','source')
        with self.db() as c:
            c.execute('INSERT INTO delivery_tdd VALUES (?,?)',('source',json.dumps(dict(mode='controller_test_first',
                implementation_task='source',test_task='source',red={'test_sha256':{'tests/test_new.py':'a'*64}}))))
        with self.assertRaises(ValueError):policy.paths(self.b,'issue','source')
        with self.db() as c:c.execute("UPDATE native_bindings SET agent_id='other' WHERE task_id='source'")
        with self.assertRaises(ValueError):policy.paths(self.b,'issue','source')

    def test_unsafe_paths_missing_frozen_tests_and_partial_reads_are_rejected(self):
        for path in ('/workspace/../secret','/workspace/.git/config','/outside/app.py'):
            with self.db() as c:c.execute("UPDATE issue_editables SET path=? WHERE path LIKE '%app.js'",(path,))
            with self.assertRaises(ValueError):policy.paths(self.b,'issue','source')
            with self.db() as c:c.execute("UPDATE issue_editables SET path='/workspace/app.js' WHERE path=?",(path,))
        required=['/delivery/app.js']
        for reads in ({},{required[0]:dict(lines=True,total_lines=True)},
                      {required[0]:dict(lines=1,total_lines=2)}):
            with self.assertRaises(ValueError):policy.require_complete(required,reads)
        policy.require_complete(required,{required[0]:dict(lines=2,total_lines=2)})
        with self.db() as c:c.execute("DELETE FROM issue_editables WHERE path LIKE '%test_new.py'")
        with self.assertRaises(ValueError):policy.paths(self.b,'issue','source')

    def test_legacy_non_test_first_routes_are_not_inferred_as_current_contract(self):
        with self.db() as c:c.execute('UPDATE delivery_routes SET config=?',(json.dumps(dict(enabled=True)),))
        self.assertIsNone(policy.paths(self.b,'issue','source'))
