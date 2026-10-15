import hashlib
import importlib.util
import json
from pathlib import Path
from contextlib import ExitStack
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from broker import generic_calibration_local_recovery as recovery,generic_calibration_workflow as workflow,handoffs
from broker import controller_maintenance as maintenance
from generic_harness_calibration import digest
import test_calibration_capability_wrapper as samples


class LocalWrapperTests(unittest.TestCase):
    def setUp(self):
        f=samples.CapabilityWrapperTests();f.setUp();self.addCleanup(f.doCleanups);self.f=f
        f.migrate();self.con=f.con
        self.c,self.s=map(json.loads,self.con.execute('SELECT config,state FROM generic_calibration_workflows').fetchone())
        self.s.update(stage='blocked',category='bundle_task_failed',observed_task=f.task['id'],wakeup_id=f.task['wakeup_id'])
        self.con.execute('UPDATE generic_calibration_workflows SET state=?',(json.dumps(self.s),))
        self.con.execute('CREATE TABLE IF NOT EXISTS tool_events(request_id TEXT,tool_count INTEGER)')
        handoffs.save(self.con,f.author,f.issue,'test_first_blocked','cto',
            dict(calibration_prerequisite=self.s,error='generic_calibration_prerequisite:bundle_task_failed'),0)
        self.value=dict(passed=True,sources={n:hashlib.sha256(Path(importlib.util.find_spec(n).origin).read_bytes()).hexdigest()
            for n in recovery.SOURCES},rejections=[dict(operation='local_request_rejection_v1',execution_id='cto',
            request_sha256='a'*64,stage='read_dispatch',origin=dict(module='deterministic_read_dispatch',line=55),
            exception_type='ValueError',error_sha256=hashlib.sha256(b'invalid deterministic read contract').hexdigest(),
            retry_authorized=False,delivery_approval=False)])
        self.calls=[]
        def docker(method,path,body=None):
            self.calls.append((method,path))
            if path.endswith('-model-proxy-1/json'):return dict(Id='proxy',Image='sha256:'+'a'*64,State=dict(Running=True),
                Config=dict(Labels={'com.docker.compose.project':f.b.PREFIX,'com.docker.compose.service':'model-proxy'}))
            if method=='POST' and path=='/containers/proxy/exec':return dict(Id='probe')
            if method=='GET' and path=='/exec/probe/json':return dict(Running=False,ExitCode=0)
            raise AssertionError('unexpected Docker operation')
        f.b.docker=docker
        class Connection:
            def request(_,method,path,body,headers):self.calls.append((method,path))
            def getresponse(_):return SimpleNamespace(status=200,read=lambda n:json.dumps(self.value).encode())
            def close(_):pass
        f.b.DockerConnection=lambda *a,**k:Connection()

    def migrate(self):
        with ExitStack() as stack:
            stack.enter_context(patch.object(maintenance,'native_active',return_value=[]))
            stack.enter_context(patch.object(maintenance,'current',return_value=self.f.barrier))
            stack.enter_context(patch.object(workflow,'Effects',return_value=self.f.fx))
            return recovery.migrate(self.f.b,self.f.issue,self.f.author,self.f.operation)

    def test_wrapper_collects_closed_native_binding_proxy_ledger_and_exact_source_hashes(self):
        r=self.migrate();self.assertEqual(r['failed_execution'],'cto');self.assertFalse(r['author_restarted'])
        self.assertEqual(sum(m=='POST' for m,p in self.calls),2)
        before=list(self.calls);self.assertEqual(self.migrate(),r);self.assertEqual(self.calls,before)

    def test_wrong_installed_source_or_unbound_ledger_never_reopens_work(self):
        self.value['sources']['deterministic_read_dispatch']='0'*64
        with self.assertRaises(ValueError):self.migrate()
        self.assertEqual(self.s,json.loads(self.con.execute('SELECT state FROM generic_calibration_workflows').fetchone()[0]))
        self.assertEqual(self.con.execute('SELECT count(*) FROM generic_calibration_local_recoveries').fetchone()[0],0)
