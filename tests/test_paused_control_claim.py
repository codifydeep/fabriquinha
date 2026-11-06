import json
import sqlite3
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from fabriquinha.board import Run
from fabriquinha.control_submission import previous_submission


class PausedControlClaim(unittest.TestCase):
    def test_only_confirmed_unstarted_pause_claim_preserves_scheduled_plan(self):
        c=sqlite3.connect(':memory:')
        self.addCleanup(c.close)
        c.row_factory=sqlite3.Row
        c.executescript("""
        create table task_runs(id integer,task_id text,outcome text,summary text,error text,worker_pid integer,worker_started_at integer,ended_at integer);
        create table task_events(id integer,task_id text,run_id integer,kind text,payload text);
        insert into task_runs values(1,'card','scheduled',null,null,null,null,1);
        insert into task_runs values(2,'card','spawn_failed',null,'operational pause; no worker started',null,null,2);
        """)
        c.execute('insert into task_events values(?,?,?,?,?)',(1,'card',1,'scheduled',json.dumps({'reason':json.dumps({'control_wait':'wait'})})))
        c.execute('insert into task_events values(?,?,?,?,?)',(2,'card',2,'spawn_failed',json.dumps(dict(error='operational pause; no worker started',infrastructure=True,retry_status='ready'))))
        live=Run('card',3,'backend','implementation',False,'backend','release','contract')
        store=Mock();store.receipt.return_value={'binding':{**live.binding(),'number':1},'payload':{'submission':'sealed'}}
        self.assertEqual(previous_submission(c,store,live),'sealed')
        c.execute('update task_runs set worker_pid=123 where id=2')
        self.assertIsNone(previous_submission(c,store,live))
        c.execute('update task_runs set worker_pid=null where id=2')
        c.execute('delete from task_events where run_id=2')
        self.assertIsNone(previous_submission(c,store,live))
