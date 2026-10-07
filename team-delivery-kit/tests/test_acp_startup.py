import copy
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from broker import acp_startup as startup,worker_creation_intent as intents
from acp_wrapper import await_startup


class StartupTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);(self.root/'native.json').write_text('{}')
        @contextmanager
        def db():
            con=sqlite3.connect(self.root/'state.sqlite',timeout=1)
            con.row_factory=sqlite3.Row
            try:
                with con:yield con
            finally:con.close()
        self.b=SimpleNamespace(db=db,LOCK=threading.RLock(),STATE=self.root,SESSIONS={},
            failure_category=lambda error:type(error).__name__,assert_review_task_running=Mock())
        class DockerTimeout(TimeoutError):
            operation='containers_start'
        self.b.DockerOperationTimeout=DockerTimeout
        self.token='a'*64
        self.current=dict(scope='scope',mode='implementation',issue_id='issue')
        self.native=SimpleNamespace(task_binding=Mock(side_effect=lambda *args:dict(self.current)))
        self.native_patch=patch.dict(sys.modules,{'native':self.native});self.native_patch.start();self.addCleanup(self.native_patch.stop)
        self.payload=dict(Image='sha256:'+'b'*64,User='10000:10000',Entrypoint=['python'],Cmd=['sleep'],NetworkDisabled=False,
            Labels={'delivery-kit.owner':'owner'},Env=[],HostConfig={'ReadonlyRootfs':True})
        self.info=dict(Id='c'*64,Image=self.payload['Image'],Config={k:copy.deepcopy(v) for k,v in self.payload.items() if k not in ('Image','HostConfig')},
            HostConfig=copy.deepcopy(self.payload['HostConfig']),State={'Status':'created'})
        self.operations=[]
        def docker(method,path):
            self.operations.append((method,path))
            if method=='POST':self.info['State']['Status']='running';return {}
            return copy.deepcopy(self.info)
        self.b.docker=Mock(side_effect=docker)
        def open_transport(row,result,scope):
            self.assertEqual(scope,'scope');self.b.SESSIONS[row['request_id']]=object();return result
        self.b.open_granted_transport=Mock(side_effect=open_transport)
        self.b.execute_grant=Mock()
        with db() as con:
            con.execute('CREATE TABLE grants(digest TEXT,task_id TEXT,attempt INTEGER,mode TEXT,request_id TEXT,deadline REAL,used INTEGER)')
            con.execute('CREATE TABLE native_bindings(request_id TEXT,task_id TEXT,agent_id TEXT,scope TEXT,issue_id TEXT)')
            con.execute('CREATE TABLE leases(request_id TEXT,scenario TEXT,name TEXT,status TEXT,deadline REAL)')
            con.execute('CREATE TABLE broker_errors(request_id TEXT,operation TEXT,category TEXT,at REAL)')
            con.execute('INSERT INTO grants VALUES (?,?,?,?,?,?,?)',(hashlib.sha256(self.token.encode()).hexdigest(),'task',1,'implementation','request',time.time()+480,1))
            con.execute("INSERT INTO native_bindings VALUES ('request','task','agent','scope','issue')")
            con.execute('INSERT INTO leases VALUES (?,?,?,?,?)',('request','acp-session','owned','creating',time.time()+420))
            intents.record(con,'request',self.payload);intents.uncertain(con,'request')
            startup.initialize(con)
            self.state=dict(stage='pending',deadline=time.time()+90,required_action='observe_worker_startup',delivery_approval=False)
            con.execute('INSERT INTO acp_startups VALUES (?,?)',('request',json.dumps(self.state)))

    def test_late_create_is_started_once_and_opens_one_transport_under_same_grant(self):
        with patch.object(startup.time,'sleep'):
            startup.run(self.b,self.token,'request',self.state)
        self.assertEqual(self.state_saved()['stage'],'ready')
        self.b.execute_grant.assert_not_called();self.b.open_granted_transport.assert_called_once()
        self.assertEqual([op for op in self.operations if op[0]=='POST'],[('POST','/containers/owned/start')])
        for _ in range(2):
            self.assertEqual(startup.request(self.b,self.token,{},begin=False)['startup_status'],'ready')
        self.b.open_granted_transport.assert_called_once()
        self.assertFalse(self.state_saved()['delivery_approval'])

    def state_saved(self):
        with self.b.db() as con:return json.loads(con.execute('SELECT state FROM acp_startups').fetchone()[0])

    def test_unknown_start_after_restart_is_only_observed_not_repeated(self):
        with self.b.db() as con:
            con.execute('UPDATE worker_creation_intents SET state=?',(json.dumps({'stage':'start_intent'}),))
        self.info['State']['Status']='running'
        startup.run(self.b,self.token,'request',self.state)
        self.assertEqual(self.state_saved()['stage'],'ready')
        self.assertTrue(all(op[0]=='GET' for op in self.operations))
        self.b.execute_grant.assert_not_called()

    def test_lost_transport_intent_is_terminal_not_reopened(self):
        with self.b.db() as con:
            con.execute('UPDATE acp_startups SET state=?',(json.dumps({**self.state,'stage':'transport_intent'}),))
        with patch.object(startup.threading,'Thread') as thread:
            result=startup.request(self.b,self.token,{},begin=False)
        self.assertEqual(result['startup_status'],'failed');thread.assert_not_called()
        self.b.open_granted_transport.assert_not_called()

    def test_ready_record_without_live_session_cannot_fake_readiness(self):
        with self.b.db() as con:
            con.execute('UPDATE acp_startups SET state=?',(json.dumps({**self.state,'stage':'ready','result':{'status':'running'}}),))
            con.execute("UPDATE leases SET status='running'")
        result=startup.request(self.b,self.token,{},begin=False)
        self.assertEqual(result['startup_status'],'failed');self.assertEqual(result['category'],'startup_transport_lost')

    def test_native_cancellation_blocks_start_and_records_failure(self):
        self.native.task_binding.side_effect=ValueError('not running')
        startup.run(self.b,self.token,'request',self.state)
        self.assertEqual(self.state_saved()['stage'],'failed');self.b.docker.assert_not_called()
        self.b.open_granted_transport.assert_not_called()

    def test_image_drift_is_not_started_or_adopted(self):
        self.info['Image']='foreign'
        startup.run(self.b,self.token,'request',self.state)
        self.assertEqual(self.state_saved()['stage'],'failed')
        self.assertTrue(all(op[0]=='GET' for op in self.operations));self.b.open_granted_transport.assert_not_called()

    def test_expired_or_stale_authority_cannot_poll(self):
        with self.b.db() as con:con.execute('UPDATE grants SET deadline=0')
        with self.assertRaises(ValueError):startup.request(self.b,self.token,{},begin=False)
        with self.b.db() as con:
            con.execute('UPDATE grants SET deadline=?',(time.time()+480,))
            con.execute('INSERT INTO grants VALUES (?,?,?,?,?,?,?)',('new','task',2,'implementation','new-request',time.time()+480,0))
        with self.assertRaises(ValueError):startup.request(self.b,self.token,{},begin=False)

    def test_pending_polls_do_not_create_duplicate_threads_or_call_execute(self):
        worker=Mock();worker.is_alive.return_value=True
        with patch.dict(startup.THREADS,{'request':worker}),patch.object(startup.threading,'Thread') as thread:
            for _ in range(3):self.assertEqual(startup.request(self.b,self.token,{},begin=True)['startup_status'],'pending')
            thread.assert_not_called()
        self.b.execute_grant.assert_not_called()

    def test_consumed_capability_without_startup_intent_cannot_be_replayed(self):
        with self.b.db() as con:con.execute('DELETE FROM acp_startups')
        with self.assertRaises(ValueError):startup.request(self.b,self.token,{},begin=True)
        self.b.execute_grant.assert_not_called()

    def test_deadline_failure_does_not_retry_or_open_transport(self):
        startup.run(self.b,self.token,'request',{**self.state,'deadline':0})
        self.assertEqual(self.state_saved()['category'],'startup_deadline')
        self.b.execute_grant.assert_not_called();self.b.open_granted_transport.assert_not_called()

    def test_start_timeout_is_not_reposted_after_running_observation(self):
        original=self.b.docker.side_effect
        def docker(method,path):
            result=original(method,path)
            if method=='POST':raise self.b.DockerOperationTimeout()
            return result
        self.b.docker.side_effect=docker
        with patch.object(startup.time,'sleep'):
            startup.run(self.b,self.token,'request',self.state)
        self.assertEqual(self.state_saved()['stage'],'ready')
        self.assertEqual(len([op for op in self.operations if op[0]=='POST']),1)

    def test_transient_inspection_failure_does_not_restart_or_fail_worker(self):
        self.info['State']['Status']='running'
        with self.b.db() as con:
            con.execute('UPDATE worker_creation_intents SET state=?',(json.dumps({'stage':'start_outcome_unknown'}),))
        original=self.b.docker.side_effect
        self.b.docker.side_effect=[self.b.DockerOperationTimeout(),original('GET','/containers/owned/json')]
        with patch.object(startup.time,'sleep'):
            startup.run(self.b,self.token,'request',self.state)
        self.assertEqual(self.state_saved()['stage'],'ready')
        self.assertTrue(all(c.args[0]=='GET' for c in self.b.docker.call_args_list))

    def test_fresh_startup_consumes_once_then_waits_for_same_lease(self):
        with self.b.db() as con:con.execute('UPDATE grants SET used=0')
        def consume(*args,**kwargs):
            with self.b.db() as con:con.execute('UPDATE grants SET used=1')
            error=self.b.DockerOperationTimeout();error.operation='containers_create';raise error
        self.b.execute_grant.side_effect=consume
        with patch.object(startup.time,'sleep'):
            startup.run(self.b,self.token,'request',self.state)
        self.assertEqual(self.state_saved()['stage'],'ready')
        self.b.execute_grant.assert_called_once_with(self.token,{},streaming=True,defer_transport=True)


class WrapperStartupTests(unittest.TestCase):
    def test_pending_polls_use_no_second_open_or_grant(self):
        call=Mock(side_effect=[{'startup_status':'pending'},{'startup_status':'pending'},{'startup_status':'ready','resume_session_id':'s'}])
        result=await_startup(call,sleep=Mock())
        self.assertEqual(result['resume_session_id'],'s')
        self.assertEqual([c.args[0] for c in call.call_args_list],['/v1/acp-startup','/v1/acp-ready','/v1/acp-ready'])

    def test_wrapper_fails_on_terminal_startup_not_fake_initialize(self):
        with self.assertRaises(RuntimeError):await_startup(Mock(return_value={'startup_status':'failed'}))

    def test_wrapper_wait_has_bounded_deadline(self):
        call=Mock(return_value={'startup_status':'pending'})
        with self.assertRaises(TimeoutError):await_startup(call,clock=Mock(side_effect=[0,96]),sleep=Mock())
        call.assert_called_once_with('/v1/acp-startup',{})
