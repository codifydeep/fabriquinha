import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from coordination_store import CoordinationStore
from handoff_bridge import sync_handoffs


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store=CoordinationStore(Path(self.tmp.name)/'ledger.db')
        self.addCleanup(self.store.close)
        self.store.create_attempt('r2','b2','v0.1')
        self.db=sqlite3.connect(':memory:')
        self.db.row_factory=sqlite3.Row
        self.addCleanup(self.db.close)
        self.db.executescript('''
          CREATE TABLE tasks(id TEXT,title TEXT,assignee TEXT);
          CREATE TABLE task_runs(id INTEGER,profile TEXT);
          CREATE TABLE task_events(id INTEGER,task_id TEXT,run_id INTEGER,kind TEXT,payload TEXT,created_at INTEGER);
          INSERT INTO tasks VALUES('t1','Implement','cto');
          INSERT INTO task_runs VALUES(7,'techlead');
          INSERT INTO task_runs VALUES(8,'cto');
          INSERT INTO task_events VALUES(1,'t1',7,'review_requested','{"implementer":"techlead","reviewer":"cto"}',100);
          INSERT INTO task_events VALUES(2,'t1',8,'claimed','{"source_status":"review"}',101);
        ''')
        self.config=dict(attempt='r2',board='b2')

    def test_real_claim_records_acceptance_and_replay_is_idempotent(self):
        self.assertEqual(sync_handoffs(self.db,self.config,self.store),2)
        self.assertEqual(sync_handoffs(self.db,self.config,self.store),0)
        receipt=self.store.get('r2','handoff','claim:2:run:8')
        self.assertEqual(receipt['status'],'accepted')
        self.assertEqual(receipt['recipient'],'cto')
        self.assertEqual(receipt['run_id'],'8')

    def test_wrong_reviewer_claim_is_rejected(self):
        self.db.execute("UPDATE task_runs SET profile='frontend' WHERE id=8")
        with self.assertRaises(ValueError):
            sync_handoffs(self.db,self.config,self.store)

    def test_retry_has_distinct_receipt(self):
        sync_handoffs(self.db,self.config,self.store)
        self.db.execute("INSERT INTO task_runs VALUES(9,'cto')")
        self.db.execute("INSERT INTO task_events VALUES(3,'t1',9,'claimed','{\"source_status\":\"review\"}',105)")
        sync_handoffs(self.db,self.config,self.store)
        self.assertEqual(self.store.get('r2','handoff','claim:3:run:9')['run_id'],'9')
        self.assertEqual(self.store.get('r2','handoff','claim:2:run:8')['run_id'],'8')
