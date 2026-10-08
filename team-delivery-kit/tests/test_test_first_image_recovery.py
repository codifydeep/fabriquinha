import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch
from broker import test_first_image_recovery as recovery,controller_maintenance as maintenance,native,failed_test_checkpoint as checkpoint

TASK='22222222-2222-4222-8222-222222222222'


class CanonicalImageRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.con=sqlite3.connect(':memory:');self.con.row_factory=sqlite3.Row;self.addCleanup(self.con.close)
        schemas=('failed_test_checkpoint_executions(issue_id TEXT,source_task TEXT,receipt TEXT)',
            'test_first_red(issue_id TEXT)','leases(request_id TEXT,status TEXT)',
            'delivery_routes(issue_id TEXT,config TEXT)','test_first_jobs(job_key TEXT,identity TEXT,state TEXT)',
            'failed_execution_snapshots(task_id TEXT,volume TEXT,status TEXT)',
            'native_bindings(task_id TEXT,request_id TEXT)','grants(request_id TEXT,mode TEXT)',
            'harness_qualifications(task_id TEXT,state TEXT)')
        for schema in schemas:self.con.execute('CREATE TABLE '+schema)
        self.route=dict(issue_id='issue',enabled=True,test_first=True,author='author',techlead='peer',test_first_files=['tests/test_new.py'])
        self.saved=dict(status='rejected',failure_type='ValueError',failure_sha256=hashlib.sha256(b'fixed test-first job isolation drift').hexdigest(),
            route_sha256=checkpoint.digest(self.route),snapshot_volume='snapshot',request_id='request',delivery_approved=False)
        self.image='sha256:'+'a'*64
        payload=dict(Image='runtime@'+self.image,User='10000:10000',Entrypoint=['python'],Cmd=['-m','unittest'],
            NetworkDisabled=True,Env=[],Labels={'delivery-kit.owner':'owner'},HostConfig={'NetworkMode':'none','ReadonlyRootfs':True})
        self.identity=dict(name='exact-red',payload=payload)
        self.info=dict(Id='exact',Image=self.image,Config=copy.deepcopy(payload),HostConfig=payload['HostConfig'],
            State=dict(Status='created',Running=False,StartedAt='0001-01-01T00:00:00Z'))
        rows=(('failed_test_checkpoint_executions',('issue',TASK,json.dumps(self.saved))),
            ('delivery_routes',('issue',json.dumps(self.route))),('leases',('request','closed')),
            ('native_bindings',(TASK,'request')),('grants',('request','implementation')),
            ('test_first_jobs',(TASK+':red',json.dumps(self.identity),json.dumps(dict(stage='create_intent',deadline=1)))),
            ('failed_execution_snapshots',(TASK,'snapshot','complete')),('harness_qualifications',(TASK,json.dumps({'stage':'passed'}))))
        for table,values in rows:self.con.execute('INSERT INTO '+table+' VALUES('+','.join('?' for _ in values)+')',values)
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        root=Path(directory.name);(root/'native.json').write_text('{}')
        @contextmanager
        def db():yield self.con;self.con.commit()
        self.calls=[]
        def docker(method,path,payload=None):
            self.calls.append((method,path))
            if path.startswith('/images/'):return dict(Id=self.image,Config={'Env':[]})
            if path.startswith('/volumes/'):return dict(Labels={'delivery-kit.owner':'owner','delivery-kit.source-task':TASK})
            return self.info
        self.b=SimpleNamespace(db=db,LOCK=threading.RLock(),STATE=root,OWNER='owner',docker=docker)
        self.source=dict(id=TASK,issue_id='issue',agent_id='author',status='failed')

    def run_recovery(self,barrier=None):
        with (patch.object(maintenance,'current',return_value=barrier or dict(stage='sealed',drained=True,operation_id='maintenance')),
                patch.object(native,'task_record',return_value=self.source),patch.object(native,'issue_task_runs',return_value=[self.source])):
            return recovery.resume(self.b,TASK)

    def test_preserves_checkpoint_and_handle_no_creation_start_or_author_retry(self):
        value=self.run_recovery()
        self.assertEqual(value['status'],'capturing')
        proof=value['canonical_image_recovery']
        self.assertEqual(proof['previous_checkpoint'],self.saved)
        self.assertEqual(proof['container_id'],'exact')
        self.assertFalse(proof['author_restarted']);self.assertFalse(proof['start_replayed'])
        self.assertFalse(proof['delivery_approval'])
        self.assertEqual(self.run_recovery(),value)
        self.assertTrue(all(method=='GET' for method,path in self.calls))

    def test_started_wrong_image_or_unsealed_job_cannot_resume(self):
        original=copy.deepcopy(self.info)
        for change in (dict(Image='sha256:'+'b'*64),dict(State={'Status':'running','Running':True,'StartedAt':'2026'})):
            self.info={**original,**change}
            with self.assertRaises(ValueError):self.run_recovery()
        self.info=original
        with self.assertRaises(ValueError):self.run_recovery(dict(stage='released',drained=True))
