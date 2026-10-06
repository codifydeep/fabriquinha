from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
from broker import handoffs
from broker.test_size_recovery import reopen


class SizeRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.con=sqlite3.connect(':memory:');self.con.row_factory=sqlite3.Row
        self.addCleanup(self.con.close);handoffs.initialize(self.con)
        self.con.execute('CREATE TABLE test_revision_trials(issue_id TEXT,config TEXT,state TEXT)')
        self.con.execute('CREATE TABLE test_first_red(issue_id TEXT,receipt TEXT)')
        self.con.execute('CREATE TABLE leases(status TEXT)')
        self.issue='11111111-1111-4111-8111-111111111111'
        self.source='22222222-2222-4222-8222-222222222222'
        self.review='33333333-3333-4333-8333-333333333333'
        self.payload={'issue_id':self.issue,'source_task':self.source,'review_task':self.review,'manifest_sha256':'a'*64}
        self.state={'status':'approved','source_task':self.source,'review_task':self.review,
                    'manifest_sha256':'a'*64,'wakeup_id':'wake','reason':'Original approval',
                    'read_evidence':{'test':'observed'}}
        self.red={'task_id':self.source,'volume':'frozen','red':{'manifest_sha256':'a'*64,
                  'test_sha256':{'tests/test_new.py':'b'*64}}}
        self.con.execute('INSERT INTO delivery_routes VALUES (?,?)',(self.issue,json.dumps({
            'enabled':False,'test_first_files':['tests/test_new.py'],'cto':'cto'})))
        self.con.execute('INSERT INTO test_revision_trials VALUES (?,?,?)',(
            self.issue,json.dumps({'reviewer':'lead'}),json.dumps(self.state)))
        self.con.execute('INSERT INTO test_first_red VALUES (?,?)',(self.issue,json.dumps(self.red)))
        @contextmanager
        def db():yield self.con
        root=Path(self.tmp.name);(root/'native.json').write_text('{}')
        self.broker=SimpleNamespace(db=db,LOCK=threading.RLock(),STATE=root)
        self.measure=Mock(return_value={'manifest_sha256':'a'*64,'files':{
            'tests/test_new.py':{'sha256':'b'*64,'bytes':38510}}})
        self.runs=[{'id':self.review,'status':'completed','agent_id':'lead','wakeup_id':'wake'}]

    def test_invalidation_preserves_review_red_and_is_idempotent(self):
        with patch('broker.native.issue_task_runs',return_value=self.runs):
            first=reopen(self.broker,self.payload,measurement=self.measure)
            self.assertEqual(reopen(self.broker,self.payload,measurement=self.measure),first)
        self.measure.assert_called_once()
        self.assertEqual(first['prior_review']['reason'],'Original approval')
        self.assertEqual(first['oversized_test_bytes'],{'tests/test_new.py':38510})
        self.assertEqual(json.loads(self.con.execute('SELECT receipt FROM test_first_red').fetchone()[0]),self.red)
        state=json.loads(self.con.execute('SELECT state FROM test_revision_trials').fetchone()[0])
        self.assertEqual(state['status'],'blocked')

    def test_valid_sized_snapshot_cannot_be_invalidated(self):
        self.measure.return_value['files']['tests/test_new.py']['bytes']=32768
        with patch('broker.native.issue_task_runs',return_value=self.runs):
            with self.assertRaisesRegex(ValueError,'no oversized'):reopen(self.broker,self.payload,measurement=self.measure)

    def test_live_worker_or_changed_snapshot_rejected(self):
        self.con.execute("INSERT INTO leases VALUES ('running')")
        with self.assertRaisesRegex(ValueError,'paused idle'):reopen(self.broker,self.payload,measurement=self.measure)
        self.con.execute('DELETE FROM leases')
        with self.assertRaisesRegex(ValueError,'exact approved'):
            reopen(self.broker,{**self.payload,'manifest_sha256':'c'*64},measurement=self.measure)
