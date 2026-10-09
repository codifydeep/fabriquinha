import contextlib
import copy
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from broker import validation_job as job

TASK='22222222-2222-4222-8222-222222222222'


class ValidationJobTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'db';self.info=None;self.calls=[]
        self.uncertain_create=False;self.uncertain_start=False
        self.payload=dict(Image='sha256:'+'a'*64,User='10000:10000',Entrypoint=['python'],
            Cmd=['-m','unittest','discover'],Env=['PYTHONDONTWRITEBYTECODE=1'],Labels={},
            NetworkDisabled=True,HostConfig=dict(NetworkMode='none',ReadonlyRootfs=True))
        self.b=SimpleNamespace(PREFIX='delivery-kit-test',OWNER='owner',db=self.db,
            docker=self.docker,docker_stdout=lambda *a,**k:'Ran 323 tests\nOK')
    @contextlib.contextmanager
    def db(self):
        con=sqlite3.connect(self.path);con.row_factory=sqlite3.Row
        try:
            with con:yield con
        finally:con.close()
    def docker(self,method,path,payload=None):
        self.calls.append((method,path))
        if path.startswith('/images/'):return dict(Id='sha256:'+'a'*64,Config=dict(Env=[]))
        if method=='POST' and '/create' in path:
            self.info=dict(Id='exact',Image='sha256:'+'a'*64,Config=copy.deepcopy(payload),
                HostConfig=copy.deepcopy(payload['HostConfig']),State=dict(Status='created',ExitCode=0))
            if self.uncertain_create:raise TimeoutError('create')
        elif method=='POST' and path.endswith('/start'):
            self.info['State']['Status']='running'
            if self.uncertain_start:raise TimeoutError('start')
        elif method=='GET':return self.info
    def call(self,now=1):return job.run(self.b,TASK,'suite',self.payload,now=now)
    def test_uncertain_effects_are_observed_once_and_result_survives_cleanup_failure(self):
        self.uncertain_create=True
        with self.assertRaises(job.Pending):self.call()
        self.uncertain_start=True
        with self.assertRaises(job.Pending):self.call(2)
        self.info['State']['Status']='exited'
        with patch('broker.helper_cleanup.schedule',side_effect=TimeoutError('cleanup')):
            result=self.call(3)
        self.assertEqual(result['exit_code'],0);self.assertFalse(result['approval'])
        self.info=None
        self.assertEqual(self.call(4),result)
        self.assertEqual(sum(m=='POST' and '/create' in p for m,p in self.calls),1)
        self.assertEqual(sum(m=='POST' and p.endswith('/start') for m,p in self.calls),1)
        self.assertFalse(any(m=='DELETE' for m,p in self.calls))
    def test_missing_handle_cannot_recreate_and_deadline_does_not_approve(self):
        self.uncertain_create=True
        with self.assertRaises(job.Pending):self.call()
        self.info=None
        with self.assertRaises(job.Pending):self.call(2)
        with self.assertRaises(ValueError):self.call(602)
        self.assertEqual(sum(m=='POST' for m,p in self.calls),1)
    def test_isolation_drift_is_rejected_and_jobs_are_grouped(self):
        with self.assertRaises(job.Pending):self.call()
        self.assertEqual(self.info['Config']['Labels']['com.docker.compose.project'],'delivery-kit-test-tests')
        self.info['HostConfig']['NetworkMode']='bridge'
        with self.assertRaises(ValueError):self.call(2)
    def test_failure_result_is_durable_not_success(self):
        with self.assertRaises(job.Pending):self.call()
        self.info['State'].update(Status='exited',ExitCode=1)
        result=self.call(2)
        self.assertEqual(result['exit_code'],1)
        self.assertFalse(result['approval'])
    def test_only_fixed_kinds_and_canonical_tasks(self):
        for task,kind in ((TASK,'shell'),('wrong','suite')):
            with self.assertRaises(ValueError):job.run(self.b,task,kind,self.payload)

    def test_large_test_failure_log_is_complete_and_cached_without_reexecution(self):
        import hashlib
        output='AssertionError: '+('source context\n'*8000)
        def read_log(*args, **kwargs):
            self.assertEqual(kwargs['limit'],1048576)
            self.assertTrue(kwargs['include_stderr'])
            return output
        self.b.docker_stdout=read_log
        with self.assertRaises(job.Pending):self.call()
        self.info['State'].update(Status='exited',ExitCode=1)
        result=self.call(2)
        self.assertEqual(result['output'],output)
        self.assertEqual(result['output_sha256'],hashlib.sha256(output.encode()).hexdigest())
        self.assertEqual(result['exit_code'],1)
        self.assertFalse(result['approval'])
        self.info=None
        self.assertEqual(self.call(3),result)
        self.assertEqual(sum(m=='POST' and p.endswith('/start') for m,p in self.calls),1)

    def test_oversized_test_log_cannot_produce_receipt_or_restart_job(self):
        def read_log(*args, **kwargs):raise RuntimeError('validator output unavailable')
        self.b.docker_stdout=read_log
        with self.assertRaises(job.Pending):self.call()
        self.info['State'].update(Status='exited',ExitCode=1)
        for now in (2,3):
            with self.assertRaises(RuntimeError):self.call(now)
        with self.db() as con:
            state=json.loads(con.execute('select state from validation_jobs').fetchone()[0])
        self.assertNotIn('result',state)
        self.assertEqual(sum(m=='POST' and p.endswith('/start') for m,p in self.calls),1)

    def test_green_log_uses_test_bound_but_structure_retains_small_bound(self):
        for kind,limit in (('green',1048576),('structure',65536)):
            with self.subTest(kind=kind):
                self.info=None
                with self.assertRaises(job.Pending):job.run(self.b,TASK,kind,self.payload,now=1)
                self.info['State'].update(Status='exited',ExitCode=0)
                with patch.object(self.b,'docker_stdout',return_value='OK') as read:
                    job.run(self.b,TASK,kind,self.payload,now=2)
                self.assertEqual(read.call_args.kwargs['limit'],limit)
