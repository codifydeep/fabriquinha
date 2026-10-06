import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from review_controller import Controller,bounded_run

class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name); self.board=self.root/'board'; self.board.mkdir()
        self.work=self.board/'workspaces/t_one'; self.work.mkdir(parents=True)
        (self.work/'score.py').write_text('original')
        self.db=sqlite3.connect(self.board/'kanban.db'); self.addCleanup(self.db.close)
        self.db.executescript('''CREATE TABLE tasks(id,status,current_run_id,claim_lock,title,assignee,workspace_path);
        CREATE TABLE task_events(id,task_id,run_id,kind,payload);
        INSERT INTO task_events VALUES(1,'t_one',1,'claimed','{}');''')
        self.db.execute('INSERT INTO tasks VALUES(?,?,?,?,?,?,?)',('t_one','running',1,'lock','feature','backend_data',str(self.work))); self.db.commit()
        self.controller=Controller(self.board,self.root/'private','attempt','volume','image')
        self.addCleanup(self.controller.db.close)

    def request(self,operation,run=1,**kwargs):
        return self.controller.handle(dict(operation=operation,task='t_one',run=run,claim='lock',**kwargs))

    def review(self):
        revision=self.request('freeze',reviewer='techlead')['revision']
        self.db.execute("UPDATE tasks SET current_run_id=2,assignee='techlead'")
        self.db.execute("INSERT INTO task_events VALUES(2,'t_one',2,'claimed',?)",(json.dumps({'source_status':'review'}),)); self.db.commit()
        return revision

    def test_approval_requires_this_review_validation(self):
        revision=self.review()
        with self.assertRaisesRegex(ValueError,'no passing'): self.request('approve',2,revision=revision)
        with patch.object(self.controller,'validate',return_value=dict(passed=True)):
            self.request('validate',2,revision=revision)
        self.assertTrue(self.request('approve',2,revision=revision)['approved'])

    def test_changes_decision_requires_actual_validation(self):
        revision=self.review()
        with self.assertRaisesRegex(ValueError,'review_validate required'):
            self.request('decision',2,revision=revision)
        with patch.object(self.controller,'validate',return_value=dict(passed=False,output='actual test failure')):
            self.request('validate',2,revision=revision)
        self.assertTrue(self.request('decision',2,revision=revision,reason='[FUNCTIONAL] actual assertion failed')['decision_allowed'])

    def test_passing_tests_reject_unsupported_functional_finding(self):
        revision=self.review()
        with patch.object(self.controller,'validate',return_value=dict(passed=True)):
            self.request('validate',2,revision=revision)
        with self.assertRaisesRegex(ValueError,'passing tests'):
            self.request('decision',2,revision=revision,reason='four tests fail')

    def test_document_rework_protects_code_and_new_files(self):
        revision=self.review()
        (self.board/'validation-contracts.json').write_text(json.dumps({'t_one':{'immutable_review':True}}))
        self.db.execute("INSERT INTO task_events VALUES(3,'t_one',2,'changes_requested',?)",(json.dumps({'reason':'[DOCUMENTATION] Add notes only'}),))
        self.db.execute("INSERT INTO task_events VALUES(4,'t_one',3,'claimed','{}')")
        self.db.execute("UPDATE tasks SET current_run_id=3,assignee='backend_data'"); self.db.commit()
        self.assertEqual(self.request('rework_check',3)['revision'],revision)
        (self.work/'score.py').write_text('changed')
        with self.assertRaisesRegex(ValueError,'protected delivery'): self.request('rework_check',3)
        (self.work/'score.py').write_text('original')
        (self.work/'test_extra.py').write_text('unauthorized')
        with self.assertRaisesRegex(ValueError,'unauthorized file'): self.request('rework_check',3)

    def test_stale_approval_rejected(self):
        revision=self.review()
        with self.assertRaisesRegex(ValueError,'stale revision'): self.request('approve',2,revision='0'*64)
        with self.assertRaisesRegex(PermissionError,'stale'): self.request('approve',1,revision=revision)

    def test_reviewer_cannot_freeze_replacement(self):
        self.review()
        with self.assertRaises(PermissionError): self.request('freeze',2,reviewer='cto')

    def test_mutated_source_does_not_mutate_snapshot(self):
        revision=self.review()
        (self.work/'score.py').write_text('changed')
        self.assertEqual(self.request('inspect',2)['files']['score.py'],'original')
        with patch.object(self.controller,'validate',return_value=dict(passed=True)):
            self.request('validate',2,revision=revision)
        with self.assertRaisesRegex(ValueError,'delivery_changed'): self.request('approve',2,revision=revision)

    def test_controller_restart_reuses_frozen_delivery(self):
        first=self.request('freeze',reviewer='techlead')
        second=Controller(self.board,self.root/'private','attempt','volume','image')
        try:
            result=second.handle(dict(operation='freeze',task='t_one',run=1,claim='lock',reviewer='techlead'))
            self.assertEqual(first['revision'],result['revision'])
        finally: second.db.close()

    def test_validation_output_is_bounded(self):
        with self.assertRaisesRegex(ValueError,'test_output_limit'):
            bounded_run([sys.executable,'-c','print("x"*1024)'],limit=16)

    def test_validation_has_deadline(self):
        import subprocess
        with self.assertRaises(subprocess.TimeoutExpired):
            bounded_run([sys.executable,'-c','import time; time.sleep(2)'],timeout=0.05)

    def test_review_denial_is_durable_and_idempotent(self):
        self.review()
        self.request('denial',2,tool='write_file')
        self.request('denial',2,tool='write_file')
        self.assertEqual(self.controller.db.execute('SELECT count(*) FROM denials').fetchone()[0],1)

    def test_controller_rejects_arbitrary_operation(self):
        revision=self.review()
        with self.assertRaises(PermissionError): self.request('shell',2,revision=revision)

    def diagnosis(self):
        revision=self.review()
        self.db.execute("UPDATE tasks SET status='blocked',current_run_id=NULL,claim_lock=NULL WHERE id='t_one'")
        self.db.execute("INSERT INTO task_events VALUES(3,'t_one',1,'review_requested','{}')")
        self.db.execute("INSERT INTO task_events VALUES(4,'t_one',2,'blocked','{}')")
        self.db.execute('INSERT INTO tasks VALUES(?,?,?,?,?,?,?)',('t_diag','running',3,'diag','INCIDENT-t_one','cto',str(self.work)))
        self.db.commit()
        return revision

    def diag_request(self,op,**args):
        return self.controller.handle(dict(operation=op,task='t_diag',run=3,claim='diag',**args))

    def test_resume_is_scoped_and_durable(self):
        revision=self.diagnosis()
        self.assertTrue(self.diag_request('diagnose')['can_resume'])
        receipt=self.diag_request('resume',revision=revision,block_event=4)
        self.db.execute("UPDATE tasks SET status='review' WHERE id='t_one'"); self.db.commit()
        self.assertEqual(receipt,self.diag_request('resume',revision=revision,block_event=4))
        self.assertEqual(self.controller.db.execute('SELECT count(*) FROM approvals').fetchone()[0],0)

    def test_resume_rejects_obsolete_identity_and_event(self):
        revision=self.diagnosis()
        for args in [dict(revision='obsolete',block_event=4),dict(revision=revision,block_event=3)]:
            with self.assertRaises(PermissionError): self.diag_request('resume',**args)

    def test_resume_rejects_changed_delivery(self):
        revision=self.diagnosis(); (self.work/'score.py').write_text('changed')
        self.assertFalse(self.diag_request('diagnose')['can_resume'])
        with self.assertRaises(PermissionError): self.diag_request('resume',revision=revision,block_event=4)

    def test_resume_rejects_wrong_owner_and_ceo_question(self):
        revision=self.diagnosis()
        self.db.execute("UPDATE tasks SET assignee='produto' WHERE id='t_diag'"); self.db.commit()
        self.assertFalse(self.diag_request('diagnose')['can_resume'])
        self.db.execute("UPDATE tasks SET assignee='cto' WHERE id='t_diag'")
        self.db.execute("UPDATE task_events SET payload=? WHERE id=4",(json.dumps({'reason':'[DECISION:scope]'}),)); self.db.commit()
        with self.assertRaises(PermissionError): self.diag_request('resume',revision=revision,block_event=4)
