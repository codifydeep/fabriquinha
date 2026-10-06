import json
from pathlib import Path
import sqlite3
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from review_block_event import review_block_event

class CrashReviewTests(unittest.TestCase):
    def test_only_verified_review_crash_can_resume(self):
        db=sqlite3.connect(':memory:'); self.addCleanup(db.close); db.row_factory=sqlite3.Row
        db.executescript('CREATE TABLE task_events(id INTEGER PRIMARY KEY,task_id,run_id,kind,payload); CREATE TABLE task_runs(id,task_id,ended_at,outcome);')
        for i,kind,payload in [(1,'review_requested',{}),(2,'claimed',{'source_status':'review'}),
                (3,'crashed',{'retry_status':'review','pid':123}),
                (4,'gave_up',{'retry_status':'review','trigger_outcome':'crashed','pid':123})]:
            db.execute('INSERT INTO task_events VALUES(?,?,?,?,?)',(i,'t_one',7,kind,json.dumps(payload)))
        db.execute('INSERT INTO task_runs VALUES(?,?,?,?)',(7,'t_one',99,'crashed'))
        self.assertEqual(review_block_event(db,'t_one')['id'],4)
        db.execute("UPDATE task_runs SET ended_at=NULL")
        self.assertIsNone(review_block_event(db,'t_one'))
        db.execute("UPDATE task_runs SET ended_at=99")
        db.execute("UPDATE task_events SET payload=? WHERE kind='claimed'",(json.dumps({'source_status':'ready'}),))
        self.assertIsNone(review_block_event(db,'t_one'))
