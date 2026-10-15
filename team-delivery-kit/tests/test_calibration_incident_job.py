import copy
import json
import sqlite3
from types import SimpleNamespace
import unittest
from broker import calibration_incident_job as jobs
from calibration_transport_probe import run,source_hashes


class IncidentJobTests(unittest.TestCase):
    def test_json_probe_has_separate_image_identity_and_no_extra_authority(self):
        from calibration_json_transport_probe import run as json_run,source_hashes as json_sources
        self.b.CALIBRATION_JSON_PROBE_IMAGE=self.b.CALIBRATION_TRANSPORT_PROBE_IMAGE
        self.proof=json_run()
        with self.assertRaises(TimeoutError):jobs.run(self.b,self.con,'e'*64,json_sources(),now=1,kind='json')
        r=jobs.run(self.b,self.con,'e'*64,json_sources(),now=2,kind='json')
        self.assertEqual(json.loads(r['output'])['operation'],'fixed_json_object_transport_probe_v1')
        _,payload=jobs.payload(self.b,'e'*64,'json')
        self.assertIn('/calibration_json_transport_probe.py',payload['Cmd'][1])
        self.assertEqual(payload['HostConfig']['NetworkMode'],'none');self.assertEqual(payload['HostConfig']['Mounts'],[])
        self.assertEqual(payload['Labels']['com.docker.compose.project'],'delivery-kit-port2-tests')
        with self.assertRaises(ValueError):jobs.run(self.b,self.con,'e'*64,source_hashes(),now=3)

    def setUp(self):
        self.con=sqlite3.connect(':memory:');self.addCleanup(self.con.close)
        self.b=SimpleNamespace(PREFIX='delivery-kit-port2',OWNER='owned',CALIBRATION_TRANSPORT_PROBE_IMAGE='sha256:'+'a'*64)
        self.calls=[];self.container={};self.uncertain=None;self.proof=run()
        def docker(method,path,body=None):
            if path.startswith('/images/'):return dict(Id=self.b.CALIBRATION_TRANSPORT_PROBE_IMAGE,Config=dict(Env=['PATH=/usr/bin']))
            self.calls.append((method,path))
            if method=='GET':return copy.deepcopy(self.container) if self.container else None
            if path.startswith('/containers/create'):
                self.container.update(Id='probe',Image=body['Image'],Config={k:copy.deepcopy(v) for k,v in body.items() if k!='HostConfig'},
                    HostConfig=copy.deepcopy(body['HostConfig']),Mounts=[],State=dict(Status='created',ExitCode=0))
                if self.uncertain=='create':raise TimeoutError()
            else:
                self.container['State']=dict(Status='exited',ExitCode=0)
                if self.uncertain=='start':raise TimeoutError()
        self.b.docker=docker;self.b.docker_stdout=lambda *a,**k:json.dumps(self.proof)

    def test_fixed_job_is_isolated_and_unknown_ack_never_repeats_effects(self):
        for phase in ('create','start',None):
            f=IncidentJobTests();f.setUp();self.addCleanup(f.doCleanups);f.uncertain=phase
            for now in range(1,5):
                try:r=jobs.run(f.b,f.con,'b'*64,source_hashes(),now=now)
                except TimeoutError:f.uncertain=None
                else:break
            self.assertEqual(sum(m=='POST' for m,p in f.calls),2)
            self.assertEqual(json.loads(r['output'])['model_calls'],0)
            before=list(f.calls);self.assertEqual(jobs.run(f.b,f.con,'b'*64,source_hashes(),now=1000),r)
            self.assertEqual(f.calls,before)
            _,p=jobs.payload(f.b,'b'*64)
            self.assertEqual(p['HostConfig']['Mounts'],[]);self.assertEqual(p['HostConfig']['NetworkMode'],'none')
            self.assertEqual(p['Cmd'][0],'-c');self.assertIn('signal.alarm(90)',p['Cmd'][1])
            self.assertEqual(p['Labels']['com.docker.compose.project'],'delivery-kit-port2-tests')

    def test_forged_authority_is_preserved_as_rejection_not_retried(self):
        self.proof['delivery_approval']=True
        with self.assertRaises(TimeoutError):jobs.run(self.b,self.con,'b'*64,source_hashes(),now=1)
        with self.assertRaises(ValueError):jobs.run(self.b,self.con,'b'*64,source_hashes(),now=2)
        before=list(self.calls)
        with self.assertRaises(ValueError):jobs.run(self.b,self.con,'b'*64,source_hashes(),now=3)
        self.assertEqual(self.calls,before)

    def test_elapsed_deadline_observes_a_completed_probe_instead_of_discarding_evidence(self):
        with self.assertRaises(TimeoutError):jobs.run(self.b,self.con,'b'*64,source_hashes(),now=1)
        self.assertEqual(json.loads(jobs.run(self.b,self.con,'b'*64,source_hashes(),now=1000)['output'])['passed'],True)

    def test_docker_null_empty_mounts_is_accepted_but_any_real_mount_stays_forbidden(self):
        original=self.b.docker
        def native(method,path,body=None):
            value=original(method,path,body)
            if method=='GET' and value and 'HostConfig' in value:value['HostConfig']['Mounts']=None
            return value
        self.b.docker=native
        with self.assertRaises(TimeoutError):jobs.run(self.b,self.con,'b'*64,source_hashes(),now=1)
        self.assertTrue(json.loads(jobs.run(self.b,self.con,'b'*64,source_hashes(),now=2)['output'])['passed'])
        info=copy.deepcopy(self.container);info['HostConfig']['Mounts']=None
        info['Mounts']=[dict(Type='volume',Name='foreign',Destination='/secret',RW=False)]
        _,expected=jobs.payload(self.b,'b'*64)
        with self.assertRaises(ValueError):jobs.verify_job(self.b,info,expected)
