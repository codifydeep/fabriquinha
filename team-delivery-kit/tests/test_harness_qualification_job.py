import copy,json,sqlite3,unittest
from types import SimpleNamespace
from unittest.mock import patch
from broker import harness_qualification as job
from service_mode_harness_qualification import TEST,CASES,fixture
import hashlib


class HarnessJobTests(unittest.TestCase):
    def setUp(self):
        self.b=SimpleNamespace(IMAGE='sha256:'+'a'*64,OWNER='owned',PREFIX='delivery-kit-port2')
        self.b.docker=lambda *a:dict(Id=self.b.IMAGE,Config=dict(Env=['PATH=/usr/bin']))
        self.prepared=dict(manifest_sha256='b'*64,test_sha256={TEST:'c'*64})

    def result(self):
        return dict(operation='service_mode_harness_calibration_v1',status='passed',manifest_sha256='b'*64,
            test_sha256='c'*64,product_green=False,red_approved=False,delivery_approval=False,
            compile=dict(manifest_sha256='b'*64,test_sha256='c'*64,**{k:dict(exit_code=0) for k in ('control','harness','product')}),
            positive=dict(tests=15,failures=0,errors=0,skipped=0,unexpected_successes=0,expected_failures=0),
            negative_controls={case:dict(tests=1,failures=1,errors=0,skipped=0,unexpected_successes=0,expected_failures=0) for case in CASES},
            control_fixture_sha256={case:hashlib.sha256(fixture(case).encode()).hexdigest() for case in ['positive',*CASES]})

    def test_no_socket_credentials_network_writable_delivery_or_arbitrary_command(self):
        p=job.payload(self.b,'task','volume','b'*64)
        info=dict(Config={k:v for k,v in p.items() if k!='HostConfig'},HostConfig=p['HostConfig'])
        job.verify_job(info,p)
        for mutate in (lambda i:i['HostConfig']['Mounts'][0].update(ReadOnly=False),
                       lambda i:i['HostConfig'].update(NetworkMode='bridge'),
                       lambda i:i['Config'].update(Cmd=['sh','-c','untrusted']),
                       lambda i:i['Config'].update(Env=['OPENROUTER_API_KEY=forbidden'])):
            bad=copy.deepcopy(info);mutate(bad)
            with self.assertRaises(ValueError):job.verify_job(bad,p)

    def test_proof_cannot_accept_wrong_snapshot_skips_or_runtime_errors(self):
        value=self.result();job.validate_result(value,self.prepared)
        for mutate in (lambda r:r.update(manifest_sha256='d'*64),lambda r:r.update(product_green=True),
                       lambda r:r['compile']['harness'].update(exit_code=1),
                       lambda r:r['negative_controls']['probe_timeout'].update(errors=1,failures=0),
                       lambda r:r['positive'].update(skipped=1),
                       lambda r:r['control_fixture_sha256'].update(positive='e'*64)):
            bad=copy.deepcopy(value);mutate(bad)
            with self.assertRaises(ValueError):job.validate_result(bad,self.prepared)

    def test_uncertain_creation_is_observed_without_second_post(self):
        con=sqlite3.connect(':memory:');self.addCleanup(con.close)
        calls=[]
        def docker(method,path,body=None):
            if path.startswith('/images/'):
                return dict(Id=self.b.IMAGE,Config=dict(Env=['PATH=/usr/bin']))
            calls.append(method)
            if method=='POST':raise TimeoutError('unknown acknowledgement')
            return None
        self.b.docker=docker
        from broker import remediation_runtime_guard as guard
        with patch.object(guard,'qualified',return_value=dict(amendment={'operation':'fixed'},cto='cto')):
            with self.assertRaises(TimeoutError):job.capture(self.b,con,'issue','task','volume',self.prepared)
            with self.assertRaises(ValueError):job.capture(self.b,con,'issue','task','volume',self.prepared)
        self.assertEqual(calls,['POST','GET'])
        self.assertEqual(json.loads(con.execute('SELECT state FROM harness_qualifications').fetchone()[0])['stage'],'create_intent')

    def test_inherited_environment_is_exact_and_credentials_are_rejected(self):
        env=job.image_environment(self.b)
        self.assertEqual(env,['PATH=/usr/bin','PYTHONDONTWRITEBYTECODE=1'])
        for values in [['OPENROUTER_API_KEY=forbidden'],['PATH=/bin','PATH=/other']]:
            self.b.docker=lambda *a:dict(Id=self.b.IMAGE,Config=dict(Env=values))
            with self.assertRaises(ValueError):job.image_environment(self.b)
