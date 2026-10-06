import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from coordination_store import CoordinationStore
from e2e_controller import ATTEMPT
import e2e_fault
from durable_notifications import flush


class FaultTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name); self.store=CoordinationStore(self.root/'coord.db'); self.addCleanup(self.store.close)
        self.store.create_attempt(ATTEMPT,ATTEMPT,'test')
        self.db=sqlite3.connect(':memory:'); self.db.row_factory=sqlite3.Row; self.addCleanup(self.db.close)
        self.db.executescript("CREATE TABLE tasks(id,status,worker_pid,current_run_id,claim_lock); INSERT INTO tasks VALUES('t_build','running',123,1,'claim');")
        self.data=dict(attempt=ATTEMPT,cards={'build':'t_build'},inject_worker_failure=True)
        (self.root/'e2e.json').write_text(json.dumps(self.data))
        work=self.root/'workspaces/t_build'; work.mkdir(parents=True)
        (work/'e2e-fault-ready.json').write_text(json.dumps(dict(task='t_build',run=1,green_run=1,claim='claim')))
        self.config=dict(attempt=ATTEMPT,db_path=self.root/'kanban.db',coordination_path=self.root/'coord.db')
        self.env={b'HERMES_KANBAN_TASK':b't_build',b'HERMES_KANBAN_RUN_ID':b'1',b'HERMES_KANBAN_CLAIM_LOCK':b'claim'}
    def test_injection_is_one_time_and_identity_bound(self):
        with patch.object(e2e_fault,'identity',return_value=(self.env,'start')),patch.object(e2e_fault.os,'kill') as kill:
            self.assertTrue(e2e_fault.tick(self.db,self.config,self.store,1))
            self.assertFalse(e2e_fault.tick(self.db,self.config,self.store,2))
            self.assertEqual(kill.call_count,1)
    def test_wrong_process_is_not_killed(self):
        with patch.object(e2e_fault,'identity',return_value=({},'start')),patch.object(e2e_fault.os,'kill') as kill:
            with self.assertRaises(PermissionError): e2e_fault.tick(self.db,self.config,self.store,1)
            kill.assert_not_called()
    def test_current_claim_can_resume_existing_green(self):
        self.db.execute('UPDATE tasks SET current_run_id=2')
        (self.root/'workspaces/t_build/e2e-fault-ready.json').write_text(json.dumps(dict(task='t_build',run=2,green_run=1,claim='claim')))
        env=dict(self.env); env[b'HERMES_KANBAN_RUN_ID']=b'2'
        with patch.object(e2e_fault,'identity',return_value=(env,'start')),patch.object(e2e_fault.os,'kill') as kill:
            self.assertTrue(e2e_fault.tick(self.db,self.config,self.store,1)); kill.assert_called_once()
    def test_restart_between_intent_and_kill(self):
        self.data['inject_supervisor_restart']=True
        (self.root/'e2e.json').write_text(json.dumps(self.data))
        with patch.object(e2e_fault,'identity',return_value=(self.env,'start')),patch.object(e2e_fault.os,'kill') as kill:
            with patch.object(e2e_fault.os,'getpid',return_value=200),patch.object(e2e_fault.os,'_exit',side_effect=SystemExit):
                with self.assertRaises(SystemExit): e2e_fault.tick(self.db,self.config,self.store,1)
            kill.assert_not_called()
            with patch.object(e2e_fault.os,'getpid',return_value=201): e2e_fault.tick(self.db,self.config,self.store,2)
            self.assertEqual(kill.call_count,1)
        self.assertTrue(self.store.get(ATTEMPT,'e2e_fault','green-worker-interruption')['observer_restart_observed'])
    def test_outbox_retry_survives_new_store_instance(self):
        self.store.enqueue(ATTEMPT,'e2e-outbox-probe',json.dumps(dict(profile='techlead',chat_id=0,text='probe')))
        calls=[]
        self.assertEqual(flush(self.config,lambda *a:calls.append(a),lambda _: 'token'),0)
        self.assertFalse(calls)
        self.assertEqual(flush(self.config,lambda *a:calls.append(a),lambda _: 'token'),1)
        self.assertEqual(len(calls),1)
