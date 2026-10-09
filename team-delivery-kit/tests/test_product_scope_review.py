import contextlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from broker import product_scope_review as policy


class ScopeReviewTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.path=Path(temp.name)/'state.sqlite'
        self.b=SimpleNamespace(db=self.db)
        with self.db() as con:
            con.executescript('CREATE TABLE product_scope_task_bases(task_id TEXT);'
                'CREATE TABLE native_bindings(request_id TEXT,issue_id TEXT,agent_id TEXT,task_id TEXT);'
                'CREATE TABLE grants(request_id TEXT,mode TEXT);'
                'CREATE TABLE review_assignments(review_agent_id TEXT,source_task_id TEXT,volume TEXT);'
                'CREATE TABLE snapshots(task_id TEXT,volume TEXT,status TEXT);'
                'CREATE TABLE delivery_routes(issue_id TEXT,config TEXT);'
                'CREATE TABLE reviews(review_task_id TEXT,source_task_id TEXT,reviewer_agent_id TEXT,manifest_sha256 TEXT,status TEXT);')
            con.execute('INSERT INTO native_bindings VALUES (?,?,?,?)',('request','issue','reviewer','review'))
            con.execute('INSERT INTO grants VALUES (?,?)',('request','review'))
            con.execute('INSERT INTO review_assignments VALUES (?,?,?)',('reviewer','source','frozen'))
            con.execute('INSERT INTO snapshots VALUES (?,?,?)',('source','frozen','complete'))
            con.execute('INSERT INTO delivery_routes VALUES (?,?)',('issue',json.dumps(dict(enabled=True,author='author',reviewer='reviewer'))))
            con.execute('INSERT INTO reviews VALUES (?,?,?,?,?)',('review','source','reviewer','a'*64,'approved'))
        self.bound=dict(frozen_test_sha256={'tests/test_new.py':'b'*64})
        self.lookup=patch.object(policy.binding,'lookup',return_value=self.bound).start()
        self.selection=patch.object(policy.worker,'selection',return_value=dict(editable_paths=['/workspace/app.py'])).start()
        self.addCleanup(patch.stopall)
        self.fx=Mock();self.fx.task.return_value=dict(id='review',agent_id='reviewer',issue_id='issue',status='completed')
        self.fx.delivery_reads.return_value={'/delivery/app.py':dict(lines=12,total_lines=12),
                                            '/delivery/tests/test_new.py':dict(lines=8,total_lines=8)}
        self.review=dict(review_task_id='review',source_task_id='source',reviewer_agent_id='reviewer',manifest_sha256='a'*64,status='approved')

    @contextlib.contextmanager
    def db(self):
        con=sqlite3.connect(self.path)
        try:
            with con:yield con
        finally:con.close()

    def test_read_contract_binds_registered_author_snapshot_to_independent_reviewer(self):
        with patch.object(policy.execution,'NativeEffects',return_value=self.fx):
            self.assertEqual(policy.read_contract(self.b,'request'),['/delivery/app.py','/delivery/tests/test_new.py'])
        self.fx.task.assert_called_once_with('review','reviewer')
        self.assertEqual(policy.read_contract(self.b,'unknown'),None)

    def test_wrong_snapshot_or_route_role_cannot_supply_read_contract(self):
        with self.db() as con:con.execute("UPDATE snapshots SET volume='other'")
        with self.assertRaises(ValueError):policy.read_contract(self.b,'request')
        self.fx.task.assert_not_called()

    def test_planning_or_unscoped_worker_does_not_receive_review_capability(self):
        with self.db() as con:con.execute("UPDATE grants SET mode='planning'")
        self.assertIsNone(policy.read_contract(self.b,'request'))
        self.lookup.return_value=None
        self.assertIsNone(policy.paths(self.b,'issue','source'))

    def test_completed_approved_review_can_report_missing_reads_but_never_delivery_approval(self):
        self.fx.delivery_reads.return_value={}
        report=policy.inspection(self.b,'issue','source',self.review,self.fx)
        self.assertEqual(report['missing_read_paths'],report['read_paths'])
        self.assertFalse(report['delivery_approval']);self.assertFalse(report['author_restarted'])
        self.fx.wake.assert_not_called()

    def test_complete_read_receipts_satisfy_inspection_but_not_release(self):
        report=policy.inspection(self.b,'issue','source',self.review,self.fx)
        self.assertEqual(report['missing_read_paths'],[]);self.assertFalse(report['delivery_approval'])

    def test_stale_approval_or_running_reviewer_cannot_qualify_revalidation(self):
        with self.assertRaises(ValueError):policy.inspection(self.b,'issue','source',dict(self.review,manifest_sha256='c'*64),self.fx)
        self.fx.task.return_value=dict(issue_id='issue',status='running')
        with self.assertRaises(ValueError):policy.inspection(self.b,'issue','source',self.review,self.fx)

    def test_partial_empty_and_boolean_counts_are_not_inspection(self):
        for value in ({},{'lines':1,'total_lines':2},{'lines':0,'total_lines':0},{'lines':True,'total_lines':True}):
            with self.subTest(value=value):self.assertEqual(policy.missing(['/delivery/app.py'],{'/delivery/app.py':value}),['/delivery/app.py'])

    def test_missing_scope_table_keeps_legacy_review_unchanged(self):
        with self.db() as con:con.execute('DROP TABLE product_scope_task_bases')
        self.assertIsNone(policy.read_contract(self.b,'request'))
        self.lookup.assert_not_called()
