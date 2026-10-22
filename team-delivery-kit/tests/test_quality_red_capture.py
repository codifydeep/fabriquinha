"""Controller provenance tests with isolated state, never native qualification."""
import copy
import hashlib
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from broker import quality_red_capture as capture
from broker import quality_lifecycle_v2 as quality
from broker import validation_job
from broker.test_first_job import digest
from docker_grouping import grouped_create
import test_quality_lifecycle_enrollment as fixtures


class QualityRedCaptureTests(unittest.TestCase):
    def setUp(self):
        f=fixtures.QualityEnrollmentTests();f.setUp();self.addCleanup(f.doCleanups)
        self.f=f;self.b=f.b;self.plan=f.plan;self.spec=f.spec;self.issue=f.issue
        self.task='40000000-0000-4000-8000-000000000001'
        self.lead='40000000-0000-4000-8000-000000000002'
        self.b.OWNER='owned-controller';self.b.QUALITY_COPY_IMAGE='sha256:'+'c'*64
        self.b.QUALITY_RED_IMAGE='sha256:'+'a'*64;self.b.QUALITY_TECHLEAD=self.lead
        f.settings['agents'][self.lead]='planning'
        (self.b.STATE/'native.json').write_text(json.dumps(f.settings))
        self.enrolled=capture.enrollment.enroll(self.b,f.payload)
        self.native=dict(id=self.task,agent_id=f.author,issue_id=self.issue,status='completed',
            workspace_id='workspace',runtime_id='runtime',created_at='2026-10-22T00:00:00Z')
        self.binding=dict(request_id='req',task_id=self.task,agent_id=f.author,scope='owned:tests',
            issue_id=self.issue,mode='implementation',status='closed')
        with self.b.db() as con:
            con.execute('DROP TABLE native_bindings');con.execute('DROP TABLE grants')
            con.execute('CREATE TABLE native_bindings(request_id TEXT,task_id TEXT,agent_id TEXT,scope TEXT,issue_id TEXT)')
            con.execute('CREATE TABLE grants(request_id TEXT,task_id TEXT,attempt INTEGER,mode TEXT,used INTEGER,deadline REAL)')
            con.execute('INSERT INTO native_bindings VALUES(?,?,?,?,?)',('req',self.task,f.author,'owned:tests',self.issue))
            con.execute('INSERT INTO grants VALUES(?,?,?,?,?,?)',('req',self.task,1,'implementation',1,0))
            con.execute('INSERT INTO leases VALUES(?,?)',('req','closed'))
            con.execute('CREATE TABLE test_first_jobs(job_key TEXT,identity TEXT,state TEXT)')
            con.execute('CREATE TABLE validation_jobs(job_key TEXT,identity TEXT,state TEXT)')
            capture.initialize(con)
            con.execute('INSERT INTO quality_native_scopes VALUES(?,?,?,?,?)',
                ('req',self.task,self.plan['run_id'],'tests_only_v2',quality.digest(self.plan)))
        self.vol=self.b.PREFIX+'-quality-red-'+self.task
        self.prepared=dict(base_sha=self.plan['base_sha'],base_manifest_sha256='d'*64,
            baseline_test_sha256=self.plan['baseline_tests'],manifest_sha256='e'*64,
            test_sha256={'tests/test_new.py':'f'*64},test_methods={'tests/test_new.py':['test_new']},
            command=self.spec['test_command'],test_roots=self.spec['test_roots'],
            test_count_pattern=self.spec['test_count_pattern'],test_image=self.spec['test_image'])
        payload=capture.copy_payload(self.b,self.enrolled,self.task,self.binding)
        name=self.b.PREFIX+'-test-first-copy-v2-'+self.task
        payload=grouped_create('POST','/containers/create?name='+name,{**payload,
            'Labels':{**payload['Labels'],'delivery-kit.owner':self.b.OWNER,
                'delivery-kit.test-first-task':self.task,'delivery-kit.test-first-job':self.task+':copy'}},self.b.PREFIX)
        copied=json.dumps(self.prepared)
        copy_result=dict(container_id='1'*64,exit_code=0,output=copied,
            output_sha256=hashlib.sha256(copied.encode()).hexdigest(),approval=False)
        with self.b.db() as con:con.execute('INSERT INTO test_first_jobs VALUES(?,?,?)',
            (self.task+':copy',json.dumps(dict(name=name,payload=payload)),
                json.dumps(dict(stage='complete',container_id='1'*64,result=copy_result))))
        self.image=dict(Id=self.b.QUALITY_RED_IMAGE,Config=dict(User='10000:10000',
            Entrypoint=['python','/opt/quality/quality_red_observation.py'],Volumes=None,Env=[],
            Labels={'delivery-kit.component':'quality-red-observer'}))
        def docker(method,path,*args):
            if path=='/images/'+self.b.QUALITY_COPY_IMAGE+'/json':
                return dict(Id=self.b.QUALITY_COPY_IMAGE,Config=dict(Volumes=None,Env=[],
                    Labels={'delivery-kit.component':'quality-red-copy'}))
            if path.startswith('/images/'):return self.image
            if path.startswith('/volumes/'):
                if path.endswith(self.vol):return {'Labels':{'delivery-kit.owner':self.b.OWNER,
                    'delivery-kit.quality-run':self.plan['run_id'],'delivery-kit.test-first-task':self.task}}
                return {'Labels':{'delivery-kit.owner':self.b.OWNER,'delivery-kit.scope':self.binding['scope']}}
            raise AssertionError('unexpected external effect')
        self.b.docker=docker
        for name,value in [('task_record',self.native),('issue_task_runs',[self.native])]:
            p=patch.object(capture.native,name,return_value=value);self.addCleanup(p.stop);p.start()

    def red_report(self):
        facts=dict(operation='observed_red_v2',run_id=self.plan['run_id'],issue_id=self.issue,
            contract_sha256=self.plan['contract_sha256'],plan_sha256=quality.digest(self.plan),task_id=self.task,
            manifest_sha256=self.prepared['manifest_sha256'],tests={**self.plan['baseline_tests'],**self.prepared['test_sha256']},
            suite_complete=True,tests_run=2,skipped=0,errors=0,exit_code=1,
            failures=[dict(path='tests/test_new.py',method='test_new',phase='test_body',kind='assertion')])
        return dict(operation='full_suite_red_observation_v2',red=facts,base_manifest_sha256='d'*64,
            captured_output_sha256='0'*64,captured_output_bytes=0,snapshot_unchanged=True,
            execution_authorized=False,delivery_approval=False)

    def job(self,b,task,kind,payload):
        key,identity=capture.job_identity(b,task,payload)
        output=json.dumps(self.red_report())
        result=dict(container_id='2'*64,exit_code=0,output=output,
            output_sha256=hashlib.sha256(output.encode()).hexdigest(),approval=False,
            validation_job_key=key,validation_contract_sha256=digest(identity))
        with b.db() as con:
            con.execute('INSERT INTO validation_jobs VALUES(?,?,?)',
                (key,json.dumps(identity),json.dumps(dict(stage='complete',container_id='2'*64,result=result))))
        return result

    def call(self):return capture.observe(self.b,self.task)

    def test_durable_red_uses_exact_native_copy_and_executed_job_not_caller_json(self):
        with patch.object(capture.validation_job,'run',side_effect=self.job) as run:
            value=self.call()
        self.assertEqual(value['stage'],'awaiting_independent_test_review')
        self.assertEqual(value['owner'],self.f.reviewer)
        self.assertFalse(value['execution_authorized']);self.assertFalse(value['delivery_approval'])
        quality.red(self.plan,value['red'])
        run.assert_called_once()
        with patch.object(capture.validation_job,'run',side_effect=AssertionError('no replay')):
            self.assertEqual(capture.observe(SimpleNamespace(**vars(self.b)),self.task),value)

    def test_fake_job_result_without_durable_receipt_cannot_advance(self):
        with patch.object(capture.validation_job,'run',return_value=dict(exit_code=0,output=json.dumps(self.red_report()))):
            with self.assertRaises(ValueError):self.call()
        with patch.object(capture.validation_job,'run',side_effect=AssertionError('do not repeat unproven job')):
            value=self.call()
        self.assertEqual(value['stage'],'technical_blocked')
        self.assertEqual(value['incident']['category'],'red_provenance_rejected')

    def test_uncertain_job_preserves_intent_and_observes_the_same_payload(self):
        with patch.object(capture.validation_job,'run',side_effect=validation_job.Pending('observe exact handle')) as run:
            for _ in range(2):
                with self.assertRaises(validation_job.Pending):self.call()
            self.assertEqual(run.call_args_list[0],run.call_args_list[1])
        with patch.object(capture.validation_job,'run',side_effect=self.job):
            self.assertEqual(self.call()['stage'],'awaiting_independent_test_review')

    def test_red_cannot_be_captured_from_legacy_issue_or_wrong_author(self):
        with self.b.db() as con:con.execute('UPDATE native_bindings SET agent_id=?',(self.f.reviewer,))
        with self.assertRaises(ValueError):self.call()
        with self.b.db() as con:
            con.execute('UPDATE native_bindings SET agent_id=?',(self.f.author,))
            con.execute('DELETE FROM quality_lifecycle_enrollments')
        with self.assertRaises(ValueError):self.call()

    def test_phase_must_come_from_native_controller_admission_not_task_text(self):
        self.native['handoff_note']='I declare that I only wrote tests and have approved Red.'
        with self.b.db() as con:con.execute("UPDATE quality_native_scopes SET phase='implementation'")
        with patch.object(capture.validation_job,'run') as run:
            with self.assertRaises(ValueError):self.call()
            run.assert_not_called()
        with self.b.db() as con:con.execute('DELETE FROM quality_native_scopes')
        with self.assertRaises(ValueError):self.call()

    def test_open_workspace_or_incomplete_native_task_cannot_capture(self):
        with self.b.db() as con:con.execute("UPDATE leases SET status='running'")
        with self.assertRaises(ValueError):self.call()
        with self.b.db() as con:con.execute("UPDATE leases SET status='closed'")
        self.native['status']='failed'
        with self.assertRaises(ValueError):self.call()

    def test_unused_capability_cannot_claim_an_executed_source(self):
        with self.b.db() as con:con.execute('UPDATE grants SET used=0')
        with self.assertRaises(ValueError):self.call()

    def test_old_tests_attempt_cannot_hide_a_newer_implementation_grant(self):
        with self.b.db() as con:
            con.execute('INSERT INTO native_bindings VALUES(?,?,?,?,?)',
                ('later',self.task,self.f.author,'newer-scope',self.issue))
            con.execute('INSERT INTO grants VALUES(?,?,?,?,?,?)',('later',self.task,2,'implementation',1,0))
            con.execute('INSERT INTO leases VALUES(?,?)',('later','closed'))
            con.execute('INSERT INTO quality_native_scopes VALUES(?,?,?,?,?)',
                ('later',self.task,self.plan['run_id'],'implementation_v2',quality.digest(self.plan)))
        with self.assertRaises(ValueError):self.call()

    def test_copy_must_have_exact_hash_binding_and_isolation_contract(self):
        with self.b.db() as con:
            raw=con.execute('SELECT identity FROM test_first_jobs').fetchone()[0];identity=json.loads(raw)
            identity['payload']['HostConfig']['NetworkMode']='bridge'
            con.execute('UPDATE test_first_jobs SET identity=?',(json.dumps(identity),))
        with self.assertRaises(ValueError):self.call()

    def test_qualified_image_must_resolve_the_contract_and_have_no_credentials(self):
        self.image['Config']['Env']=['OPENROUTER_API_KEY=not-a-real-secret']
        with self.assertRaises(ValueError):self.call()
        self.image['Config']['Env']=[];self.image['Id']='sha256:'+'9'*64
        with self.assertRaises(ValueError):self.call()

    def test_named_workspace_alone_is_not_proof_of_native_source_ownership(self):
        original=self.b.docker
        def foreign(method,path,*args):
            value=original(method,path,*args)
            if '-work-' in path:value={'Labels':{'delivery-kit.owner':'unrelated','delivery-kit.scope':'other'}}
            return value
        self.b.docker=foreign
        with self.assertRaises(ValueError):self.call()

    def test_copy_image_cannot_inherit_anonymous_state_volumes(self):
        original=self.b.docker
        def inherited(method,path,*args):
            value=original(method,path,*args)
            if path=='/images/'+self.b.QUALITY_COPY_IMAGE+'/json':value['Config']['Volumes']={'/opt/data':{}}
            return value
        self.b.docker=inherited
        with self.assertRaises(ValueError):self.call()

    def test_failed_red_goes_to_technical_owner_without_automatic_retry(self):
        def failure(b,task,kind,payload):
            result=self.job(b,task,kind,payload)
            result.update(exit_code=2,output=json.dumps(dict(operation='rejected_red_observation_v2',
                category='suite_not_behavioral_red',execution_authorized=False,delivery_approval=False)))
            result['output_sha256']=hashlib.sha256(result['output'].encode()).hexdigest()
            with b.db() as con:
                con.execute('UPDATE validation_jobs SET state=?',
                    (json.dumps(dict(stage='complete',container_id='2'*64,result=result)),))
            return result
        with patch.object(capture.validation_job,'run',side_effect=failure):value=self.call()
        self.assertEqual(value['stage'],'technical_blocked');self.assertEqual(value['owner'],self.lead)
        self.assertEqual(value['incident']['category'],'suite_not_behavioral_red')
        with patch.object(capture.validation_job,'run',side_effect=AssertionError('no identical retry')):
            self.assertEqual(self.call(),value)

    def test_actual_job_output_cannot_drift_manifest_task_or_plan(self):
        original=self.red_report()
        changed=copy.deepcopy(original);changed['red']['manifest_sha256']='9'*64
        with patch.object(self,'red_report',return_value=changed),patch.object(capture.validation_job,'run',side_effect=self.job):
            with self.assertRaises(ValueError):self.call()

    def test_boolean_exit_status_cannot_replace_actual_process_exit_code(self):
        def wrong_type(b,task,kind,payload):
            result=self.job(b,task,kind,payload);result['exit_code']=False
            with b.db() as con:con.execute('UPDATE validation_jobs SET state=?',
                (json.dumps(dict(stage='complete',container_id='2'*64,result=result)),))
            return result
        with patch.object(capture.validation_job,'run',side_effect=wrong_type):
            with self.assertRaises(ValueError):self.call()

    def test_pending_capture_cannot_rebind_its_plan_or_source(self):
        with patch.object(capture.validation_job,'run',side_effect=validation_job.Pending('same handle')):
            with self.assertRaises(validation_job.Pending):self.call()
        with self.b.db() as con:con.execute('UPDATE native_bindings SET scope=?',('another-scope',))
        with patch.object(capture.validation_job,'run') as run:
            with self.assertRaises(ValueError):self.call()
            run.assert_not_called()

    def test_receipt_survives_retirement_of_mutable_source_records(self):
        with patch.object(capture.validation_job,'run',side_effect=self.job):expected=self.call()
        with self.b.db() as con:
            con.execute('DELETE FROM native_bindings');con.execute('DELETE FROM grants');con.execute('DELETE FROM leases')
        with patch.object(capture.validation_job,'run',side_effect=AssertionError('receipt readback only')):
            self.assertEqual(self.call(),expected)

    def test_corrupt_state_is_not_accepted_or_rewritten_as_a_fresh_receipt(self):
        with patch.object(capture.validation_job,'run',side_effect=self.job):self.call()
        corrupt=json.dumps(dict(stage='awaiting_independent_test_review',execution_authorized=True))
        with self.b.db() as con:con.execute('UPDATE quality_red_captures SET state=?',(corrupt,))
        with self.assertRaises(ValueError):self.call()
        with self.b.db() as con:self.assertEqual(con.execute('SELECT state FROM quality_red_captures').fetchone()[0],corrupt)

    def test_missing_red_in_executed_output_records_incident_without_identical_retry(self):
        with patch.object(self,'red_report',return_value=dict(operation='full_suite_red_observation_v2')),\
                patch.object(capture.validation_job,'run',side_effect=self.job):
            with self.assertRaises(ValueError):self.call()
        with patch.object(capture.validation_job,'run',side_effect=AssertionError('no repeat')):
            self.assertEqual(self.call()['incident']['category'],'red_provenance_rejected')

    def test_a_second_observer_cannot_execute_the_same_source_concurrently(self):
        from concurrent.futures import ThreadPoolExecutor
        import threading
        entered=threading.Event();release=threading.Event()
        def slow(*args):
            entered.set();release.wait(3)
            raise validation_job.Pending('same actual handle')
        with patch.object(capture.validation_job,'run',side_effect=slow) as run,ThreadPoolExecutor(max_workers=1) as pool:
            first=pool.submit(self.call)
            try:
                self.assertTrue(entered.wait(2))
                with self.assertRaises(validation_job.Pending):self.call()
                self.assertEqual(run.call_count,1)
                self.assertTrue(self.b.LOCK.acquire(blocking=False));self.b.LOCK.release()
                with self.b.db() as con:con.execute('BEGIN IMMEDIATE')
            finally:release.set()
            with self.assertRaises(validation_job.Pending):first.result()

    def test_os_lock_is_released_by_process_exit_without_replaying_a_job(self):
        import subprocess,sys
        lock=self.b.STATE/'quality-red-locks';lock.mkdir(mode=0o700)
        path=lock/(self.task+'.lock')
        program=('import fcntl,os,sys,time;f=os.open(sys.argv[1],os.O_CREAT|os.O_RDWR,0o600);'
            'fcntl.flock(f,fcntl.LOCK_EX);print("locked",flush=True);time.sleep(10)')
        child=subprocess.Popen([sys.executable,'-c',program,str(path)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            self.assertEqual(child.stdout.readline().strip(),'locked')
            with self.assertRaises(validation_job.Pending):self.call()
        finally:
            child.terminate();child.wait(timeout=3);child.stdout.close();child.stderr.close()
        with patch.object(capture.validation_job,'run',side_effect=self.job):
            self.assertEqual(self.call()['stage'],'awaiting_independent_test_review')

    def test_new_explicitly_admitted_source_preserves_previous_revision(self):
        with patch.object(capture.validation_job,'run',side_effect=self.job):first=self.call()
        previous=self.task
        self.task='40000000-0000-4000-8000-000000000009'
        self.vol=self.b.PREFIX+'-quality-red-'+self.task
        self.native['id']=self.task;self.native['created_at']='2026-10-22T01:00:00Z'
        self.prepared['manifest_sha256']='6'*64;self.prepared['test_sha256']['tests/test_new.py']='7'*64
        with self.b.db() as con:
            con.execute('INSERT INTO native_bindings VALUES(?,?,?,?,?)',
                ('revision',self.task,self.f.author,'owned:tests',self.issue))
            con.execute('INSERT INTO grants VALUES(?,?,?,?,?,?)',('revision',self.task,1,'implementation',1,0))
            con.execute('INSERT INTO leases VALUES(?,?)',('revision','closed'))
            con.execute('INSERT INTO quality_native_scopes VALUES(?,?,?,?,?)',
                ('revision',self.task,self.plan['run_id'],'tests_only_v2',quality.digest(self.plan)))
            old=con.execute('SELECT identity,state FROM test_first_jobs WHERE job_key=?',(previous+':copy',)).fetchone()
            identity=json.loads(old[0].replace(previous,self.task));state=json.loads(old[1])
            state['result']['output']=json.dumps(self.prepared)
            state['result']['output_sha256']=hashlib.sha256(state['result']['output'].encode()).hexdigest()
            con.execute('INSERT INTO test_first_jobs VALUES(?,?,?)',
                (self.task+':copy',json.dumps(identity),json.dumps(state)))
        with patch.object(capture.validation_job,'run',side_effect=self.job):second=self.call()
        self.assertNotEqual(first['red']['manifest_sha256'],second['red']['manifest_sha256'])
        with self.b.db() as con:
            self.assertEqual(con.execute('SELECT count(*) FROM quality_red_captures').fetchone()[0],2)
            self.assertEqual(json.loads(con.execute('SELECT state FROM quality_red_captures WHERE task_id=?',
                (previous,)).fetchone()[0]),first)


if __name__=='__main__':unittest.main()
