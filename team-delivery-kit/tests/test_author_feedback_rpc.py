import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sqlite3
import tarfile
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from broker import author_feedback_rpc as rpc


class AuthorFeedbackRpcTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup);self.path=Path(folder.name)/'state.sqlite'
        @contextmanager
        def db():
            c=sqlite3.connect(self.path);c.row_factory=sqlite3.Row
            try:
                with c:yield c
            finally:c.close()
        self.db=db;self.request='11111111-1111-4111-8111-111111111111'
        self.task='22222222-2222-4222-8222-222222222222';self.actor='33333333-3333-4333-8333-333333333333'
        self.issue='44444444-4444-4444-8444-444444444444';self.wake='55555555-5555-4555-8555-555555555555'
        self.cfg=dict(task_id=self.task,author=self.actor,issue_id=self.issue,wakeup_id=self.wake,
            source_task='66666666-6666-4666-8666-666666666666',note_sha256='a'*64,
            previous_volume='delivery-kit-port2-test-first-origin',previous_manifest_sha256='b'*64,
            test_path='tests/test.py',image='sha256:'+'c'*64,worker_image='sha256:'+'7'*64,feedback_sha256='d'*64,max_candidates=4,
            expected=dict(initial_expected=1,poll_minimum=3,stale_expected='Newest matching: #11'))
        with db() as c:
            c.executescript('CREATE TABLE grants(request_id,task_id,mode,used,attempt,deadline);'
                'CREATE TABLE native_bindings(request_id,task_id,agent_id,issue_id,scope);'
                'CREATE TABLE leases(request_id,name,status,deadline);')
            c.execute('INSERT INTO grants VALUES(?,?,?,?,?,?)',(self.request,self.task,'implementation',1,1,time.time()+300))
            c.execute('INSERT INTO native_bindings VALUES(?,?,?,?,?)',(self.request,self.task,self.actor,self.issue,'workspace:implementation:'+self.task))
            c.execute('INSERT INTO leases VALUES(?,?,?,?)',(self.request,'delivery-kit-port2-job-'+self.request,'running',time.time()+300))
        self.b=SimpleNamespace(db=db,LOCK=threading.RLock(),TOKEN='controller-only-secret',PREFIX='delivery-kit-port2',OWNER='owner')
        self.current=b'current test';self.sha=hashlib.sha256(self.current).hexdigest()
        self.native_patch=patch.object(rpc,'native_running');self.native=self.native_patch.start();self.addCleanup(self.native_patch.stop)
        self.bytes_patch=patch.object(rpc,'current_bytes',side_effect=lambda *args:self.current)
        self.bytes_patch.start();self.addCleanup(self.bytes_patch.stop)
        self.run_patch=patch.object(rpc.validation_job,'run',side_effect=self.result)
        self.run=self.run_patch.start();self.addCleanup(self.run_patch.stop)

    def result(self,b,task,kind,payload):
        sha=payload['Cmd'][-1]
        facts=dict(operation='literal_author_feedback_v1',candidate_sha256=sha,feedback_sha256='d'*64,
            previous_manifest_sha256='b'*64,test_path='tests/test.py',expected=self.cfg['expected'],
            reports={n:dict(initial_requests=1,poll_requests=2,stale_guard_text='Newest matching: #11' if n=='guarded' else 'Newest matching: #4')
                for n in ('guarded','unguarded')},capture=dict(field='poll_requests',literal='NODE_HARNESS',literal_line=177,
                    assignment='snap.poll_requests = latestCount();'),failed_fields=['poll_requests'],checks_passed=False,
            outside_literal_bytes_preserved=True,candidate_bytes_stable_during_measurement=True,
            evidence_scope='current_file_fixed_diagnostic_only',non_target_verification='not_performed_in_feedback',
            model_calls=0,next_action='Drive polling BEFORE the captured assignment',**{k:False for k in rpc.FALSE_FLAGS})
        raw=json.dumps(facts,sort_keys=True)
        return dict(exit_code=0,output=raw,output_sha256=hashlib.sha256(raw.encode()).hexdigest(),
            validation_job_key='e'*64,validation_contract_sha256='f'*64,approval=False)

    def test_scoped_capability_caches_failed_checks_without_approval_or_second_execution(self):
        token=rpc.issue(self.b,self.request,self.cfg)
        self.assertNotEqual(token,self.b.TOKEN)
        result=rpc.execute(self.b,token,{'candidate_sha256':self.sha})
        self.assertFalse(result['checks_passed']);self.assertFalse(result['delivery_approval'])
        self.assertEqual(rpc.execute(self.b,token,{'candidate_sha256':self.sha}),result)
        self.run.assert_called_once()
        self.assertEqual(rpc.issue(self.b,self.request,self.cfg),token)
        with self.db() as c:self.assertEqual(c.execute('SELECT count(*) FROM author_feedback_jobs').fetchone()[0],1)

    def test_closed_expired_wrong_profile_or_superseded_lease_never_executes(self):
        token=rpc.issue(self.b,self.request,self.cfg)
        for sql,undo in (("UPDATE leases SET status='closed'","UPDATE leases SET status='running'"),
                ('UPDATE leases SET deadline=0','UPDATE leases SET deadline='+str(time.time()+300)),
                ("UPDATE grants SET mode='review'","UPDATE grants SET mode='implementation'"),
                ("UPDATE native_bindings SET agent_id='other'","UPDATE native_bindings SET agent_id='"+self.actor+"'")):
            with self.db() as c:c.execute(sql)
            with self.assertRaises(ValueError):rpc.execute(self.b,token,{'candidate_sha256':self.sha})
            with self.db() as c:c.execute(undo)
        with self.db() as c:c.execute('INSERT INTO grants VALUES(?,?,?,?,?,?)',('other',self.task,'implementation',1,2,time.time()+300))
        with self.assertRaises(ValueError):rpc.execute(self.b,token,{'candidate_sha256':self.sha})
        self.run.assert_not_called()

    def test_agent_cannot_choose_path_command_image_or_reuse_admin_token(self):
        token=rpc.issue(self.b,self.request,self.cfg)
        for payload in ({},{'command':'id'},{'candidate_sha256':self.sha,'image':'latest'},
                {'candidate_sha256':self.sha,'path':'/etc/passwd'}):
            with self.assertRaises(ValueError):rpc.execute(self.b,token,payload)
        with self.assertRaises(ValueError):rpc.execute(self.b,self.b.TOKEN,{'candidate_sha256':self.sha})
        self.run.assert_not_called()

    def test_stale_current_hash_invalidates_cached_result_and_concurrent_edit_discards_new_result(self):
        token=rpc.issue(self.b,self.request,self.cfg);rpc.execute(self.b,token,{'candidate_sha256':self.sha})
        self.current=b'changed after feedback'
        with self.assertRaises(ValueError):rpc.execute(self.b,token,{'candidate_sha256':self.sha})
        current_sha=hashlib.sha256(self.current).hexdigest();real=self.result
        def changed(*args):
            result=real(*args);self.current=b'changed during measurement';return result
        self.run.side_effect=changed
        with self.assertRaises(ValueError):rpc.execute(self.b,token,{'candidate_sha256':current_sha})

    def test_pending_same_hash_observes_same_fixed_job_after_restart(self):
        token=rpc.issue(self.b,self.request,self.cfg);self.run.side_effect=rpc.validation_job.Pending('same live job')
        result=rpc.execute(self.b,token,{'candidate_sha256':self.sha})
        self.assertEqual(result['next_action'],'observe_same_feedback_job')
        first=self.run.call_args
        self.run.side_effect=self.result
        rpc.execute(self.b,token,{'candidate_sha256':self.sha})
        self.assertEqual(self.run.call_args,first)

    def test_candidate_budget_is_persistent_and_cannot_be_raised_by_reissuing(self):
        token=rpc.issue(self.b,self.request,self.cfg)
        for i in range(4):
            self.current=('candidate '+str(i)).encode();rpc.execute(self.b,token,{'candidate_sha256':hashlib.sha256(self.current).hexdigest()})
        self.current=b'fifth'
        with self.assertRaises(ValueError):rpc.execute(self.b,token,{'candidate_sha256':hashlib.sha256(self.current).hexdigest()})
        with self.assertRaises(ValueError):rpc.issue(self.b,self.request,{**self.cfg,'max_candidates':5})
        self.assertEqual(self.run.call_count,4)

    def test_cached_feedback_is_not_returned_if_lease_expires_during_current_hash_read(self):
        token=rpc.issue(self.b,self.request,self.cfg);rpc.execute(self.b,token,{'candidate_sha256':self.sha})
        def expire(*args):
            with self.db() as c:c.execute('UPDATE leases SET deadline=0')
            return self.current
        with patch.object(rpc,'current_bytes',side_effect=expire):
            with self.assertRaises(ValueError):rpc.execute(self.b,token,{'candidate_sha256':self.sha})
        self.run.assert_called_once()

    def test_fixed_payload_reads_own_workspace_without_network_credentials_or_socket(self):
        token=rpc.issue(self.b,self.request,self.cfg);rpc.execute(self.b,token,{'candidate_sha256':self.sha})
        payload=self.run.call_args.args[3];host=payload['HostConfig']
        self.assertEqual(host['NetworkMode'],'none');self.assertTrue(host['ReadonlyRootfs'])
        self.assertTrue(all(m['ReadOnly'] for m in host['Mounts']))
        own='delivery-kit-port2-work-'+hashlib.sha256(('workspace:implementation:'+self.task).encode()).hexdigest()[:32]
        self.assertEqual(host['Mounts'][1]['Source'],own)
        self.assertEqual(payload['Cmd'][0],'/literal_author_feedback.py')
        self.assertEqual(payload['Env'],['PYTHONDONTWRITEBYTECODE=1','PYTHONPATH=/'])

    def test_attachment_is_opt_in_and_rejects_wrong_worker_image(self):
        self.assertIsNone(rpc.attached_config(self.b,self.request))
        token=rpc.issue(self.b,self.request,self.cfg)
        self.b.docker=lambda *args:dict(Image=self.cfg['worker_image'])
        attached=rpc.attached_config(self.b,self.request)
        self.assertEqual(attached['capability'],token)
        self.assertNotIn('image',attached);self.assertNotIn('previous_volume',attached)
        self.b.docker=lambda *args:dict(Image='sha256:'+'8'*64)
        with self.assertRaises(ValueError):rpc.attached_config(self.b,self.request)

    def test_actual_http_dispatch_uses_only_scoped_feedback_capability(self):
        path=Path(__file__).resolve().parents[1]/'broker/server.py'
        spec=importlib.util.spec_from_file_location('isolated_feedback_dispatch',path)
        server=importlib.util.module_from_spec(spec)
        with patch.dict(os.environ,{'BROKER_WORKER_IMAGE':'sha256:'+'1'*64}):spec.loader.exec_module(server)
        server.db=self.db;server.LOCK=self.b.LOCK;server.TOKEN=self.b.TOKEN;server.OWNER=self.b.OWNER;server.PREFIX=self.b.PREFIX
        token=rpc.issue(self.b,self.request,self.cfg)
        def dispatch(bearer,body):
            handler=object.__new__(server.Handler);handler.path='/v1/author-feedback'
            raw=json.dumps(body).encode();handler.headers={'Authorization':'Bearer '+bearer,'Content-Length':str(len(raw))}
            handler.rfile=io.BytesIO(raw);handler.wfile=io.BytesIO()
            handler.send_response=lambda status:setattr(handler,'status',status)
            handler.send_header=lambda *args:None;handler.end_headers=lambda:None
            with patch.dict(sys.modules,{'author_feedback_rpc':rpc}):handler.do_POST()
            return handler.status,json.loads(handler.wfile.getvalue())
        status,value=dispatch(token,{'candidate_sha256':self.sha})
        self.assertEqual(status,200);self.assertFalse(value['delivery_approval'])
        status,value=dispatch(self.b.TOKEN,{'candidate_sha256':self.sha});self.assertEqual(status,400)
        self.assertNotIn(self.b.TOKEN,json.dumps(value))
        with self.db() as c:c.execute("UPDATE leases SET status='closed'")
        self.assertEqual(dispatch(token,{'candidate_sha256':self.sha})[0],400)
        self.assertEqual(self.run.call_count,1)

    def test_tar_reader_never_extracts_links_extra_files_or_oversized_files(self):
        def archive(name,content=b'x',link=False):
            stream=io.BytesIO()
            with tarfile.open(fileobj=stream,mode='w') as tar:
                info=tarfile.TarInfo(name);info.size=len(content)
                if link:info.type=tarfile.SYMTYPE;info.linkname='/etc/passwd';info.size=0
                tar.addfile(info,None if link else io.BytesIO(content))
            return stream.getvalue()
        self.assertEqual(rpc.archive_file(archive('test.py'),'test.py'),b'x')
        for raw in (archive('../test.py'),archive('other.py'),archive('test.py',link=True),archive('test.py',b'x'*32769)):
            with self.assertRaises(ValueError):rpc.archive_file(raw,'test.py')
