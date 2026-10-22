"""Workspace journal/provenance tests; mocked jobs do not prove Docker isolation."""
import hashlib
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from broker import quality_author_worker as worker
from docker_grouping import grouped_create
import test_quality_author_admission as fixtures


class AuthorWorkerTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.AuthorAdmissionTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.b=self.f.b;self.b.OWNER='owned';self.b.QUALITY_PREP_IMAGE='sha256:'+'a'*64
        self.grant=self.f.call();self.request=self.grant['request_id'];self.volume=None;self.posts=0;self.unknown=False
        self.calls=[]
        def docker(method,path,payload=None):
            self.calls.append((method,path))
            if path.startswith('/images/'):
                return dict(Id=self.b.QUALITY_PREP_IMAGE,Config=dict(User='10000:10000',Entrypoint=['python'],
                    Env=[],Volumes=None,Labels={'delivery-kit.component':'quality-author-prep'}))
            if method=='POST':
                self.posts+=1
                self.volume=dict(Name=payload['Name'],Driver='local',Scope='local',Labels=payload['Labels'],
                    Options=None,CreatedAt='2026-10-22T00:00:00Z')
                if self.unknown:raise TimeoutError('unknown volume ACK')
            return self.volume
        self.b.docker=docker

    def job(self,b,task,kind,payload):
        normalized=grouped_create('POST','/containers/create?name=validation',payload,b.PREFIX)
        key=worker.digest(dict(task=task,kind=kind,payload=normalized))
        expected={**normalized,'Labels':{**normalized['Labels'],'delivery-kit.owner':b.OWNER,
            'delivery-kit.source-task':task,'delivery-kit.validation-job':key}}
        identity=dict(task=task,kind=kind,name=b.PREFIX+'-validation-job-'+task+'-'+key[:12],payload=expected)
        output='' if kind=='scope_materialize' else json.dumps(dict(allowed=['tests/test_new.py'],baseline_files=3))
        result=dict(container_id='c'*64,exit_code=0,output=output,output_sha256=hashlib.sha256(output.encode()).hexdigest(),
            validation_job_key=key,validation_contract_sha256=worker.digest(identity),approval=False)
        with b.db() as con:
            con.execute('CREATE TABLE IF NOT EXISTS validation_jobs(job_key TEXT PRIMARY KEY,identity TEXT,state TEXT)')
            con.execute('INSERT INTO validation_jobs VALUES(?,?,?)',
                (key,json.dumps(identity),json.dumps(dict(stage='complete',container_id='c'*64,result=result))))
        return result

    def call(self):return worker.prepare(self.b,self.request,now=101)

    def test_seed_and_lock_fixed_jobs_produce_non_authorizing_durable_receipt(self):
        with patch.object(worker.validation_job,'run',side_effect=self.job) as job:
            receipt=self.call()
        self.assertEqual(receipt['stage'],'workspace_locked')
        self.assertFalse(receipt['worker_launch_authorized']);self.assertFalse(receipt['delivery_approval'])
        self.assertEqual(job.call_count,2);self.assertEqual(self.posts,1)
        seed,lock=[call.args[3] for call in job.call_args_list]
        self.assertEqual(seed['User'],'10000:10000');self.assertEqual(lock['User'],'0:0')
        self.assertEqual(lock['HostConfig']['CapAdd'],['CHOWN','DAC_OVERRIDE'])
        self.assertEqual(json.loads(lock['Env'][0].split('=',1)[1]),['tests/test_new.py'])
        with patch.object(worker.validation_job,'run',side_effect=AssertionError('no replay')):
            self.assertEqual(self.call(),receipt)

    def test_implementation_seed_uses_frozen_new_tests_but_locks_every_test(self):
        source=worker.admission.load
        with self.b.db() as con:context=source(con,self.request)
        context={**context,'phase':'implementation_v2'}
        selected=worker.admission.selection(self.b,self.request)
        selected={**selected,'phase':'implementation_v2','editable_paths':['/workspace/app.py'],
            'frozen_seed':dict(volume='frozen-snapshot',manifest_sha256='e'*64,test_sha256={'tests/test_new.py':'f'*64})}
        adapter=SimpleNamespace(load=lambda con,request:context,selection=lambda b,request:selected,
            enrollment=worker.admission.enrollment)
        def job(b,task,kind,payload):
            if kind=='scope_base_verify':
                # The existing fake job emits its expected allowlist. Rebind
                # this fixture report to the implementation scope, not tests.
                original=self.job(b,task,kind,payload)
                output=json.dumps(dict(allowed=['app.py'],baseline_files=3))
                updated={**original,'output':output,'output_sha256':hashlib.sha256(output.encode()).hexdigest()}
                with b.db() as con:
                    key=original['validation_job_key']
                    state=json.loads(con.execute('SELECT state FROM validation_jobs WHERE job_key=?',(key,)).fetchone()[0])
                    state['result']=updated
                    con.execute('UPDATE validation_jobs SET state=? WHERE job_key=?',(json.dumps(state),key))
                return updated
            return self.job(b,task,kind,payload)
        with patch.object(worker.validation_job,'run',side_effect=job) as jobs:
            result=worker.prepare(self.b,self.request,now=101,admission_adapter=adapter)
        self.assertEqual(result['stage'],'workspace_locked')
        seed,lock=[call.args[3] for call in jobs.call_args_list]
        self.assertIn('REVISION_SEED_JSON='+json.dumps({k:v for k,v in selected['frozen_seed'].items() if k!='volume'}),seed['Env'])
        self.assertIn(dict(Type='volume',Source='frozen-snapshot',Target='/previous',ReadOnly=True),seed['HostConfig']['Mounts'])
        self.assertEqual(json.loads(lock['Env'][0].split('=',1)[1]),['app.py'])

    def test_unknown_create_ack_is_observed_without_creating_another_volume(self):
        self.unknown=True
        with self.assertRaises(worker.validation_job.Pending):self.call()
        with patch.object(worker.validation_job,'run',side_effect=self.job):self.call()
        self.assertEqual(self.posts,1)

    def test_unregistered_volume_cannot_be_adopted(self):
        self.volume=dict(Name='foreign',Labels={})
        with self.assertRaises(ValueError):self.call()
        self.assertEqual(self.posts,0)

    def test_pending_seed_uses_same_job_and_volume_after_restart(self):
        with patch.object(worker.validation_job,'run',side_effect=worker.validation_job.Pending('running')) as job:
            for _ in range(2):
                with self.assertRaises(worker.validation_job.Pending):self.call()
            self.assertEqual(job.call_args_list[0],job.call_args_list[1])
        self.assertEqual(self.posts,1)
        with patch.object(worker.validation_job,'run',side_effect=self.job):self.call()

    def test_lost_volume_identity_or_unverified_job_cannot_authorize_worker(self):
        with patch.object(worker.validation_job,'run',side_effect=worker.validation_job.Pending('running')):
            with self.assertRaises(worker.validation_job.Pending):self.call()
        self.volume['CreatedAt']='2026-10-23T00:00:00Z'
        with self.assertRaises(ValueError):self.call()
        with self.b.db() as con:
            state=json.loads(con.execute('SELECT state FROM quality_author_workspaces').fetchone()[0])
        self.assertNotEqual(state['stage'],'workspace_locked')

    def test_expired_or_consumed_capability_is_not_prepared(self):
        for mutation in ('used=1','deadline=0'):
            with self.b.db() as con:
                con.execute('UPDATE grants SET used=0,deadline=580')
                con.execute('UPDATE grants SET '+mutation)
            with self.assertRaises(ValueError):self.call()
        self.assertEqual(self.calls,[])

    def test_worker_claim_without_durable_fixed_job_receipt_is_rejected(self):
        with self.b.db() as con:
            con.execute('CREATE TABLE validation_jobs(job_key TEXT PRIMARY KEY,identity TEXT,state TEXT)')
        with patch.object(worker.validation_job,'run',return_value=dict(exit_code=0,approval=False)):
            with self.assertRaises(ValueError):self.call()
        with self.b.db() as con:
            state=json.loads(con.execute('SELECT state FROM quality_author_workspaces').fetchone()[0])
        self.assertEqual(state['stage'],'seed_pending')

    def test_changed_native_runtime_does_not_create_workspace(self):
        settings=dict(self.f.f.settings,runtime_id='other-runtime')
        (self.b.STATE/'native.json').write_text(json.dumps(settings))
        with self.assertRaises(ValueError):self.call()
        self.assertEqual(self.calls,[])

    def test_sealed_maintenance_stops_all_preparation_effects(self):
        with self.b.db() as con:
            con.execute('INSERT INTO controller_maintenance VALUES(?,?,?)',('operation','sealed',json.dumps(dict(stage='sealed'))))
        with self.assertRaises(worker.validation_job.Pending):self.call()
        self.assertEqual(self.calls,[])


if __name__=='__main__':unittest.main()
