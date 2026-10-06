import contextlib
import copy
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from broker import durable_review_job as jobs


class DurableReviewJobTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'db.sqlite'
        self.image='sha256:'+'a'*64
        self.base=dict(volume='base',manifest_sha256='b'*64)
        self.seed=dict(task_id='source',snapshot=dict(volume='snapshot'),manifest_sha256='c'*64)
        self.proof=dict(controls_manifest_sha256='c'*64,candidate=dict(tests=261))
        self.info=None;self.creates=0;self.starts=0;self.timeout_create=False;self.timeout_start=False
        self.b=SimpleNamespace(PREFIX='project',OWNER='owner',db=self.db,docker=self.docker,
                              docker_stdout=Mock(return_value=json.dumps(self.proof)))
    @contextlib.contextmanager
    def db(self):
        con=sqlite3.connect(self.path);con.row_factory=sqlite3.Row
        try:
            with con:yield con
        finally:con.close()
    def docker(self,method,path,data=None):
        if path=='/containers/project-execution-broker-1/json':return dict(Image=self.image)
        if method=='POST' and path.startswith('/containers/create'):
            self.creates+=1
            data=copy.deepcopy(data)
            self.info=dict(Id='container',Config={k:v for k,v in data.items() if k!='HostConfig'},
                           HostConfig=data['HostConfig'],State=dict(Status='created',Running=False,ExitCode=0))
            if self.timeout_create:raise TimeoutError('lost create response')
            return dict(Id='container')
        if method=='POST' and path.endswith('/start'):
            self.starts+=1
            self.info['State']=dict(Status='exited',Running=False,ExitCode=0)
            if self.timeout_start:raise TimeoutError('lost start response')
            return {}
        if method=='GET':return self.info
        raise AssertionError((method,path))
    def run_job(self):
        with patch.object(jobs.cleanup,'schedule'):
            return jobs.run(self.b,'d'*64,self.base,self.seed,self.proof)
    def test_fixed_job_has_readonly_mounts_no_network_socket_or_credentials(self):
        result=self.run_job();self.assertEqual(result['proof'],self.proof)
        config=self.info['Config']
        self.assertEqual(config['Cmd'],['/u3_product_probe.py'])
        self.assertEqual(config['Labels']['com.docker.compose.project'],'project-tests')
        self.assertEqual(config['Labels']['com.docker.compose.service'],'job')
        self.assertEqual(self.info['HostConfig']['NetworkMode'],'none')
        self.assertEqual(config['User'],'10000:10000')
        self.assertTrue(all(m['ReadOnly'] and m['Type']=='volume' for m in self.info['HostConfig']['Mounts']))
        self.assertEqual({m['Target'] for m in self.info['HostConfig']['Mounts']},{'/base','/candidate'})
        self.assertFalse(any('TOKEN=' in value or 'KEY=' in value for value in config['Env']))
    def test_lost_create_response_is_observed_without_duplicate_create(self):
        self.timeout_create=True
        self.assertEqual(self.run_job()['proof'],self.proof)
        self.assertEqual((self.creates,self.starts),(1,1))
    def test_lost_start_response_is_observed_without_duplicate_start(self):
        self.timeout_start=True
        first=self.run_job();second=self.run_job()
        self.assertEqual(first,second)
        self.assertEqual((self.creates,self.starts),(1,1))
    def test_restart_after_start_intent_observes_same_container(self):
        original=jobs.save
        def interrupt(b,key,config,state):
            original(b,key,config,state)
            if state['phase']=='running':raise SystemExit('simulated controller restart')
        with patch.object(jobs,'save',side_effect=interrupt),patch.object(jobs.cleanup,'schedule'):
            with self.assertRaises(SystemExit):jobs.run(self.b,'d'*64,self.base,self.seed,self.proof)
        self.assertEqual(self.run_job()['proof'],self.proof)
        self.assertEqual((self.creates,self.starts),(1,1))
    def test_foreign_container_or_changed_readonly_spec_is_rejected(self):
        self.timeout_create=True
        original=self.docker
        def foreign(method,path,data=None):
            try:return original(method,path,data)
            except TimeoutError:
                self.info['Config']['Labels']['delivery-kit.owner']='foreign'
                raise
        self.b.docker=foreign
        with self.assertRaisesRegex(ValueError,'identity'):self.run_job()
        self.assertEqual(self.starts,0)
    def test_failed_tests_or_changed_proof_cannot_be_reclassified_as_success(self):
        self.b.docker_stdout.return_value=json.dumps(dict(self.proof,candidate=dict(tests=260)))
        with self.assertRaisesRegex(ValueError,'proof drift'):self.run_job()
        with self.assertRaisesRegex(ValueError,'diagnosis'):self.run_job()
        self.assertEqual(self.creates,1)
    def test_ambiguous_absent_create_never_repeats_mutation(self):
        original=self.docker
        def absent(method,path,data=None):
            if method=='POST' and path.startswith('/containers/create'):
                self.creates+=1;raise TimeoutError('request outcome unknown')
            return original(method,path,data)
        self.b.docker=absent
        with patch.object(jobs,'WINDOW',0.01),patch.object(jobs.time,'sleep'):
            with self.assertRaises(TimeoutError):self.run_job()
        self.assertEqual(self.creates,1)
        with self.assertRaisesRegex(ValueError,'diagnosis'):self.run_job()
        self.assertEqual(self.creates,1)
    def test_cleanup_error_cannot_overwrite_passed_durable_receipt(self):
        with patch.object(jobs.cleanup,'schedule',side_effect=RuntimeError('cleanup unavailable')):
            receipt=jobs.run(self.b,'d'*64,self.base,self.seed,self.proof)
        self.assertEqual(receipt['proof'],self.proof)
        self.assertEqual(self.run_job(),receipt)
    def test_changed_contract_cannot_reuse_old_key(self):
        self.run_job()
        with self.assertRaisesRegex(ValueError,'contract drift'):
            jobs.run(self.b,'d'*64,dict(self.base,volume='other'),self.seed,self.proof)
        self.assertEqual(self.creates,1)

    def test_central_docker_grouping_preserves_exact_security_identity(self):
        from docker_grouping import grouped_create
        config=jobs.specification(self.b,'d'*64,self.base,self.seed,self.proof)
        b=SimpleNamespace(PREFIX='delivery-kit-test',OWNER='owner')
        expected=jobs.payload(b,'d'*64,config)
        grouped=grouped_create('POST','/containers/create?name=test',copy.deepcopy(expected),b.PREFIX)
        info=dict(Config={k:v for k,v in grouped.items() if k!='HostConfig'},HostConfig=grouped['HostConfig'])
        jobs.identity(info,expected)
        self.assertEqual(info['Config']['Labels']['com.docker.compose.project'],'delivery-kit-test-tests')
        self.assertEqual(info['HostConfig']['NetworkMode'],'none')
        self.assertTrue(all(m['ReadOnly'] for m in info['HostConfig']['Mounts']))
