import copy
import json
import sqlite3
import unittest
from types import SimpleNamespace
from broker.test_first_job import run

TASK='22222222-2222-4222-8222-222222222222'


class TestFirstJobTests(unittest.TestCase):
    def setUp(self):
        self.con=sqlite3.connect(':memory:');self.con.row_factory=sqlite3.Row;self.addCleanup(self.con.close)
        self.info=None;self.calls=[];self.timeout_create=False;self.timeout_start=False
        self.payload=dict(Image='sha256:'+'a'*64,User='10000:10000',Entrypoint=['python'],
            Cmd=['/failed_test_checkpoint_copy.py'],Env=['TEST_FIRST_RESUME=0'],Labels={},
            NetworkDisabled=True,HostConfig=dict(NetworkMode='none',ReadonlyRootfs=True))
        def docker(method,path,payload=None):
            self.calls.append((method,path))
            if path.startswith('/images/'):return dict(Id='sha256:'+'a'*64,Config=dict(Env=[]))
            if method=='POST' and path.startswith('/containers/create'):
                self.info=dict(Id='id',Image=payload['Image'],Config=copy.deepcopy(payload),
                    HostConfig=payload['HostConfig'],State=dict(Status='created',ExitCode=0))
                if self.timeout_create:raise TimeoutError('uncertain create')
            elif method=='POST' and path.endswith('/start'):
                self.info['State']['Status']='running'
                if self.timeout_start:raise TimeoutError('uncertain start')
            elif method=='GET':return self.info
            return {}
        self.b=SimpleNamespace(PREFIX='delivery-kit-test',OWNER='owner',docker=docker,
            docker_stdout=lambda *args,**kwargs:'{"proof":true}')

    def call(self,now=1,payload=None):return run(self.b,self.con,TASK,'copy',payload or self.payload,now=now)

    def test_uncertain_create_and_start_are_observed_once(self):
        self.timeout_create=True
        with self.assertRaises(TimeoutError):self.call()
        self.timeout_start=True
        with self.assertRaises(TimeoutError):self.call(now=2)
        self.info['State']['Status']='exited'
        result=self.call(now=3)
        self.assertEqual(result['exit_code'],0)
        self.assertFalse(result['approval'])
        self.assertEqual(self.call(now=4),result)
        self.assertEqual(sum(method=='POST' and '/create' in path for method,path in self.calls),1)
        self.assertEqual(sum(method=='POST' and path.endswith('/start') for method,path in self.calls),1)
        self.assertFalse(any(method=='DELETE' for method,_ in self.calls))

    def test_resume_flag_change_preserves_first_intent_and_other_drift_is_denied(self):
        with self.assertRaises(TimeoutError):self.call()
        self.info['State']['Status']='exited'
        changed={**self.payload,'Env':['TEST_FIRST_RESUME=1']}
        self.assertEqual(self.call(now=2,payload=changed)['exit_code'],0)
        with self.assertRaises(ValueError):self.call(payload={**changed,'Cmd':['other']})

    def test_missing_handle_after_uncertain_create_never_reposts(self):
        self.timeout_create=True
        with self.assertRaises(TimeoutError):self.call()
        self.info=None
        with self.assertRaises(TimeoutError):self.call(now=2)
        with self.assertRaises(ValueError):self.call(now=602)
        self.assertEqual(sum(method=='POST' for method,_ in self.calls),1)

    def test_wrong_container_cannot_produce_receipt(self):
        with self.assertRaises(TimeoutError):self.call()
        self.info['HostConfig']['NetworkMode']='bridge'
        with self.assertRaises(ValueError):self.call(now=2)

    def test_repository_digest_matches_only_resolved_immutable_image_id(self):
        payload={**self.payload,'Image':'delivery-kit-runtime@sha256:'+'a'*64}
        # The actual Engine returns a canonical ID, not the requested reference.
        self.timeout_create=True
        with self.assertRaises(TimeoutError):self.call(payload=payload)
        self.info['Image']='sha256:'+'a'*64;self.timeout_create=False
        with self.assertRaises(TimeoutError):self.call(now=2,payload=payload)
        self.info['State']['Status']='exited'
        self.assertEqual(self.call(now=3,payload=payload)['exit_code'],0)
        self.assertEqual(sum(m=='POST' and '/create' in p for m,p in self.calls),1)

    def test_unrelated_canonical_image_is_rejected(self):
        with self.assertRaises(TimeoutError):self.call()
        self.info['Image']='sha256:'+'b'*64
        with self.assertRaises(ValueError):self.call(now=2)
