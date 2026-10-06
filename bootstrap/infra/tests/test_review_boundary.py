import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from review_boundary import intercept,worker_state

class BoundaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.db=sqlite3.connect(Path(self.tmp.name)/'kanban.db')
        self.addCleanup(self.db.close)
        self.db.executescript('''CREATE TABLE tasks(id,status,current_run_id,claim_lock,title);
        CREATE TABLE task_events(id,task_id,run_id,kind,payload);
        INSERT INTO tasks VALUES('t_one','running',2,'lock','feature');
        INSERT INTO task_events VALUES(1,'t_one',2,'claimed','{"source_status":"review"}');''')
        self.db.commit()
        self.env=patch.dict(os.environ,dict(HERMES_KANBAN_TASK='t_one',HERMES_KANBAN_DB=str(Path(self.tmp.name)/'kanban.db'),HERMES_KANBAN_RUN_ID='2',HERMES_KANBAN_CLAIM_LOCK='lock'))
        self.env.start(); self.addCleanup(self.env.stop)

    def test_review_denies_all_execution_and_write_routes(self):
        for name in ['terminal','write_file','patch','execute_code','tool_call','browser','kanban_unblock','kanban_create','read_file']:
            self.assertEqual(intercept(name,{})['error'],'operation_forbidden')

    def test_review_show_omits_implementation_body(self):
        self.assertEqual(intercept('kanban_show',{})['mode'],'review')

    def test_review_allows_fixed_operations(self):
        for name in ['review_inspect','review_validate','kanban_complete','kanban_request_changes']:
            self.assertIsNone(intercept(name,{}))

    def test_closed_claim_cannot_continue_writing(self):
        self.db.execute("UPDATE tasks SET status='review'"); self.db.commit()
        self.assertEqual(worker_state()['mode'],'closed')
        self.assertEqual(intercept('write_file',{})['error'],'operation_forbidden')

    def test_mode_cannot_be_changed_by_argument(self):
        self.assertEqual(intercept('terminal',{'mode':'implementation'})['error'],'operation_forbidden')

    def test_diagnosis_cannot_edit_author(self):
        self.db.execute("UPDATE tasks SET title='INCIDENT-t_original'"); self.db.commit()
        self.assertEqual(worker_state()['mode'],'diagnosis')
        self.assertEqual(intercept('patch',{})['error'],'operation_forbidden')

    def test_registered_incident_uses_native_claim_not_title(self):
        self.db.execute("UPDATE tasks SET title='INCIDENT-real-ci'")
        self.db.execute('UPDATE task_events SET payload=?',(json.dumps({'source_status':'ready'}),));self.db.commit()
        (Path(self.tmp.name)/'product-adapter.json').write_text(json.dumps({'cards':{'t_one':{'scope':'coordination'}}}))
        self.assertEqual(worker_state()['mode'],'implementation')
        from product_boundary import allowed
        self.assertIn('team_propose',allowed(worker_state()));self.assertNotIn('team_decide',allowed(worker_state()))
        self.db.execute('UPDATE task_events SET payload=?',(json.dumps({'source_status':'review'}),));self.db.commit()
        self.assertEqual(worker_state()['mode'],'review')
        self.assertIn('team_decide',allowed(worker_state()));self.assertNotIn('team_propose',allowed(worker_state()))
