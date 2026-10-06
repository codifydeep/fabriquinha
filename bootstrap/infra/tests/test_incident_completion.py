import json
from pathlib import Path
import sqlite3
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from incident_completion import completion_error


class CompletionTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:'); self.db.row_factory=sqlite3.Row; self.addCleanup(self.db.close)
        self.db.executescript("CREATE TABLE tasks(id,status); CREATE TABLE task_runs(id,task_id,outcome,metadata); INSERT INTO tasks VALUES('source','done'),('qa','review');")
        self.contracts={'source':{'immutable_review':True},'qa':{'immutable_review':True,'parent':'source'}}
        self.add('source',1,'backend_data','source-sha')
        self.add('qa',3,'quality_security','qa-sha','source-sha')
    def add(self,task,run,author,sha,parent=None):
        delivery=dict(revision=sha,author=author,reviewer='techlead',parent_revision=parent)
        approval=dict(delivery,approved=True,review_run=run+1)
        self.db.execute('INSERT INTO task_runs VALUES(?,?,?,?)',(run,task,'review_requested',json.dumps(dict(immutable_delivery=delivery))))
        self.db.execute('INSERT INTO task_runs VALUES(?,?,?,?)',(run+1,task,'completed',json.dumps(dict(immutable_review=approval))))
    def check(self):
        with patch('incident_completion.contracts_for',return_value=self.contracts):
            return completion_error(self.db,'source',lambda *_:None)
    def test_requires_qa_done(self):
        self.assertIn('qa',self.check())
        self.db.execute("UPDATE tasks SET status='done' WHERE id='qa'")
        self.assertIsNone(self.check())
    def test_rejects_stale_parent(self):
        self.db.execute("UPDATE tasks SET status='done' WHERE id='qa'")
        self.add('source',5,'backend_data','new-sha')
        self.assertIn('different parent',self.check())
    def test_rejects_missing_review(self):
        self.db.execute("UPDATE tasks SET status='done' WHERE id='qa'")
        self.db.execute('DELETE FROM task_runs WHERE id=4')
        self.assertIn('independent review',self.check())
