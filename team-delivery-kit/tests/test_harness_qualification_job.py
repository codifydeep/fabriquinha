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

    def test_new_scope_amendment_requires_background_proof_without_upgrading_old_receipts(self):
        from service_mode_background_qualification import BACKGROUND
        value=self.result();job.validate_result(value,self.prepared)
        with self.assertRaises(ValueError):job.validate_result(value,self.prepared,require_background=True)
        value.update(background_control=copy.deepcopy(value['positive']),
            background_fixture_sha256=hashlib.sha256((BACKGROUND+fixture('positive')).encode()).hexdigest())
        job.validate_result(value,self.prepared,require_background=True)
        for mutate in (lambda r:r['background_control'].update(tests=1),
                       lambda r:r['background_control'].update(failures=1),
                       lambda r:r.update(background_fixture_sha256='0'*64)):
            bad=copy.deepcopy(value);mutate(bad)
            with self.assertRaises(ValueError):job.validate_result(bad,self.prepared,require_background=True)

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

    def test_rejection_owner_comes_from_persistent_route_not_guard_projection(self):
        con=sqlite3.connect(':memory:');self.addCleanup(con.close)
        con.execute('CREATE TABLE delivery_routes(issue_id TEXT,config TEXT)')
        con.execute('INSERT INTO delivery_routes VALUES(?,?)',('issue',json.dumps({'cto':'actual-cto'})))
        state=job.rejection_state(con,'issue',{'Id':'job'},'rejected')
        self.assertEqual(state['owner'],'actual-cto')
        self.assertEqual(state['stage'],'blocked');self.assertFalse(state['delivery_approval'])
        with self.assertRaises(ValueError):job.rejection_state(con,'other',{'Id':'job'},'rejected')

    def test_reconcile_observes_same_failed_job_without_create_start_or_approval(self):
        con=sqlite3.connect(':memory:');self.addCleanup(con.close)
        con.execute('CREATE TABLE delivery_routes(issue_id TEXT,config TEXT)')
        con.execute('INSERT INTO delivery_routes VALUES(?,?)',('issue',json.dumps({'cto':'actual-cto'})))
        con.execute('CREATE TABLE harness_qualifications(task_id TEXT PRIMARY KEY,identity TEXT,state TEXT)')
        expected=job.payload(self.b,'task','volume','b'*64)
        identity=dict(issue_id='issue',task_id='task',volume='volume',manifest_sha256='b'*64,payload=expected)
        con.execute('INSERT INTO harness_qualifications VALUES(?,?,?)',('task',json.dumps(identity),json.dumps(dict(stage='observing',container_id='job'))))
        info=dict(Id='job',Config={k:v for k,v in expected.items() if k!='HostConfig'},
                  HostConfig=expected['HostConfig'],State=dict(Status='exited',Running=False,ExitCode=1))
        calls=[]
        original_image=self.b.IMAGE
        self.b.IMAGE='sha256:'+'d'*64  # Controller upgraded; existing job stays pinned.
        def docker(method,path,body=None):
            calls.append((method,path))
            return dict(Id=original_image,Config=dict(Env=['PATH=/usr/bin'])) if path.startswith('/images/') else info
        self.b.docker=docker;self.b.docker_stdout=lambda *args,**kwargs:'rejected'
        state=job.reconcile_rejected(self.b,con,'task')
        self.assertEqual(state['owner'],'actual-cto');self.assertFalse(state['delivery_approval'])
        self.assertTrue(all(method=='GET' for method,path in calls))
        self.assertEqual(job.reconcile_rejected(self.b,con,'task'),state)

    def test_rejection_facts_are_manifest_bound_and_never_grant_authority(self):
        con=sqlite3.connect(':memory:');self.addCleanup(con.close)
        con.execute('CREATE TABLE delivery_routes(issue_id TEXT,config TEXT)')
        con.execute('INSERT INTO delivery_routes VALUES(?,?)',('issue',json.dumps({'cto':'actual-cto'})))
        info=dict(Id='job',Config=dict(Labels={'delivery-kit.harness-manifest':'b'*64}))
        raw=dict(status='rejected',phase='positive_reference',delivery_approval=False,
                 facts=dict(manifest_sha256='b'*64,test_sha256='c'*64,positive=dict(
                     tests=15,failures=2,errors=0,skipped=0,unexpected_successes=0,expected_failures=0,
                     failed_methods=['test_demo'],source='private source',author_retry_authorized=True)))
        state=job.rejection_state(con,'issue',info,json.dumps(raw))
        self.assertEqual(state['diagnostic']['positive']['failed_methods'],['test_demo'])
        self.assertNotIn('private source',json.dumps(state))
        self.assertNotIn('author_retry_authorized',json.dumps(state))
        raw['facts']['manifest_sha256']='d'*64
        self.assertNotIn('diagnostic',job.rejection_state(con,'issue',info,json.dumps(raw)))
