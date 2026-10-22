"""Persistent delivery copy from native/Docker fixtures, not agent qualification."""
import copy
import hashlib
import json
import unittest
from unittest.mock import Mock,patch
from broker import quality_delivery_capture as capture,quality_implementation_launch as launch,acp_startup
from docker_grouping import grouped_create
import test_quality_implementation_launch as fixtures


class DeliveryCaptureTests(unittest.TestCase):
    def setUp(self):
        f=fixtures.ImplementationLaunchTests();f.setUp();self.addCleanup(f.doCleanups)
        self.f=f;self.b=f.b;self.request=f.request;f.call()
        with self.b.db() as con:
            row=dict(con.execute('SELECT * FROM grants WHERE request_id=?',(self.request,)).fetchone())
            binding=dict(con.execute('SELECT * FROM native_bindings WHERE request_id=?',(self.request,)).fetchone())
        result=acp_startup.advance_worker(self.b,row,binding)
        with self.b.db() as con:
            acp_startup.initialize(con)
            con.execute('INSERT INTO acp_startups VALUES(?,?)',(self.request,json.dumps(dict(stage='transport_intent'))))
        with patch('broker.acp_transport.Transport',return_value=Mock()):
            launch.open_transport(self.b,row,result,binding['scope'])
        with self.b.db() as con:
            for method in ('initialize','session/new','session/prompt'):
                con.execute('INSERT INTO acp_events VALUES(?,?,?,?)',(self.request,method,'green-session',1))
            con.execute('INSERT INTO acp_sessions VALUES(?,?)',(binding['scope'],'green-session'))
            con.execute("UPDATE leases SET status='closed' WHERE request_id=?",(self.request,))
        f.f.native['status']='completed';f.worker['State'].update(Status='exited',Running=False,ExitCode=0)
        self.b.QUALITY_GREEN_JOB_IMAGE='sha256:'+'e'*64
        self.volume=None;self.creates=0;self.unknown=False;old=self.b.docker
        self.name=self.b.PREFIX+'-quality-delivery-'+f.f.task
        def docker(method,path,payload=None):
            if path=='/images/'+self.b.QUALITY_GREEN_JOB_IMAGE+'/json':
                return dict(Id=self.b.QUALITY_GREEN_JOB_IMAGE,Config=dict(User='10000:10000',Env=[],Volumes=None,
                    Entrypoint=['python','/opt/quality/quality_green_job.py'],Labels={'delivery-kit.component':'quality-green-job'}))
            if path=='/volumes/'+self.name:return copy.deepcopy(self.volume)
            if path=='/volumes/create':
                self.creates+=1;self.volume=dict(Name=payload['Name'],Driver='local',Scope='local',Options=None,
                    Labels=payload['Labels'],CreatedAt='2026-10-22T04:00:00Z')
                if self.unknown:raise TimeoutError('unknown volume create acknowledgement')
                return self.volume
            return old(method,path,payload)
        self.b.docker=docker

    def copied(self,b,task,kind,payload):
        normalized=grouped_create('POST','/containers/create?name=validation',payload,b.PREFIX)
        key=capture.digest(dict(task=task,kind=kind,payload=normalized))
        expected={**normalized,'Labels':{**normalized['Labels'],'delivery-kit.owner':b.OWNER,
            'delivery-kit.source-task':task,'delivery-kit.validation-job':key}}
        identity=dict(task=task,kind=kind,name=b.PREFIX+'-validation-job-'+task+'-'+key[:12],payload=expected)
        context,_=launch.admission.handoff(b,self.f.f.source)
        files={**self.f.f.f.files,'app.py':b'VALUE=1\n'}
        inventory={p:dict(sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw)) for p,raw in files.items()}
        manifest=hashlib.sha256(json.dumps(dict(files=inventory),sort_keys=True,separators=(',',':')).encode()).hexdigest()
        report=dict(operation='post_implementation_snapshot_v2',plan_sha256=launch.admission.quality.digest(context['plan']),
            base_sha=context['plan']['base_sha'],base_manifest_sha256=context['base']['manifest_sha256'],
            reviewed_manifest_sha256=self.f.f.frozen['manifest_sha256'],
            manifest_sha256=manifest,file_inventory=inventory,tests=context['frozen_tests'],
            execution_authorized=False,delivery_approval=False)
        output=json.dumps(report)
        result=dict(container_id='f'*64,exit_code=0,output=output,output_sha256=hashlib.sha256(output.encode()).hexdigest(),
            validation_job_key=key,validation_contract_sha256=capture.digest(identity),approval=False)
        with b.db() as con:
            con.execute('INSERT INTO validation_jobs VALUES(?,?,?)',
                (key,json.dumps(identity),json.dumps(dict(stage='complete',container_id='f'*64,result=result))))
        return result

    def call(self):return capture.observe(self.b,self.request)

    def test_exact_native_completion_and_copy_yields_only_awaiting_git_not_green(self):
        with patch.object(capture.validation_job,'run',side_effect=self.copied) as job:
            receipt=self.call()
        self.assertEqual(receipt['stage'],'awaiting_git_binding')
        self.assertEqual(receipt['owner'],self.b.QUALITY_TECHLEAD)
        self.assertEqual(self.creates,1);job.assert_called_once()
        self.assertFalse(receipt['green_approved']);self.assertFalse(receipt['delivery_approval'])
        with patch.object(capture.native,'task_record',side_effect=TimeoutError),\
                patch.object(capture.validation_job,'run',side_effect=AssertionError('no replay')):
            self.assertEqual(self.call(),receipt)

    def test_unknown_volume_ack_observes_same_volume_without_another_post(self):
        self.unknown=True
        with self.assertRaises(capture.validation_job.Pending):self.call()
        with patch.object(capture.validation_job,'run',side_effect=self.copied):self.call()
        self.assertEqual(self.creates,1)

    def test_running_author_or_closing_lease_cannot_start_copy(self):
        self.f.f.native['status']='running'
        with self.assertRaises(capture.validation_job.Pending):self.call()
        self.f.f.native['status']='completed'
        with self.b.db() as con:con.execute("UPDATE leases SET status='closing' WHERE request_id=?",(self.request,))
        with self.assertRaises(capture.validation_job.Pending):self.call()
        self.assertEqual(self.creates,0)

    def test_missing_prompt_or_changed_wakeup_blocks_under_technical_owner(self):
        self.f.f.native['wakeup_id']=self.f.f.source
        receipt=self.call()
        self.assertEqual(receipt['stage'],'technical_blocked')
        self.assertEqual(receipt['owner'],self.b.QUALITY_TECHLEAD)
        self.assertFalse(receipt['incident']['automatic_retry']);self.assertEqual(self.creates,0)

    def test_recreated_snapshot_or_unjournaled_report_never_becomes_a_receipt(self):
        with patch.object(capture.validation_job,'run',side_effect=capture.validation_job.Pending('pending')):
            with self.assertRaises(capture.validation_job.Pending):self.call()
        self.volume['CreatedAt']='2026-10-22T05:00:00Z'
        self.assertEqual(self.call()['stage'],'technical_blocked')
        self.assertEqual(self.creates,1)

    def test_unjournaled_success_is_rejected_not_used_as_copy_evidence(self):
        with patch.object(capture.validation_job,'run',return_value=dict(exit_code=0,approval=False)):
            receipt=self.call()
        self.assertEqual(receipt['stage'],'technical_blocked');self.assertFalse(receipt['green_approved'])

    def test_recreated_volume_during_completed_copy_cannot_be_accepted(self):
        def replace(b,task,kind,payload):
            result=self.copied(b,task,kind,payload)
            self.volume['CreatedAt']='2026-10-22T05:00:00Z'
            return result
        with patch.object(capture.validation_job,'run',side_effect=replace):receipt=self.call()
        self.assertEqual(receipt['stage'],'technical_blocked')

    def test_closed_lease_does_not_make_a_still_running_worker_safe_to_copy(self):
        self.f.worker['State'].update(Status='running',Running=True)
        with self.assertRaises(capture.validation_job.Pending):self.call()
        self.assertEqual(self.creates,0)

    def test_copy_pending_keeps_original_job_and_deadline_across_observations(self):
        with patch.object(capture.validation_job,'run',side_effect=capture.validation_job.Pending('same job')) as job:
            for _ in range(2):
                with self.assertRaises(capture.validation_job.Pending):self.call()
            self.assertEqual(job.call_args_list[0],job.call_args_list[1])
        self.assertEqual(self.creates,1)
        with patch.object(capture.validation_job,'run',side_effect=self.copied):
            self.assertEqual(self.call()['stage'],'awaiting_git_binding')

    def test_alert_and_technical_escalation_do_not_reset_waiting_for_native_evidence(self):
        self.f.f.native['status']='running'
        for now in (1000,1700):
            with patch.object(capture.time,'time',return_value=now),self.assertRaises(capture.validation_job.Pending):self.call()
        _,state=capture.load(self.b,self.request)
        self.assertEqual(state['deadline'],2800);self.assertTrue(state['alert_due'])
        with patch.object(capture.time,'time',return_value=2801):receipt=self.call()
        self.assertEqual(receipt['stage'],'technical_blocked')
        self.assertEqual(receipt['owner'],self.b.QUALITY_TECHLEAD)
        self.assertEqual(receipt['incident']['category'],'delivery_observation_deadline')
        self.assertEqual(self.creates,0)

    def retired_worker(self,record):
        old=self.b.docker;name=self.b.PREFIX+'-job-'+self.request
        def docker(method,path,payload=None):
            if path in ('/containers/'+name+'/json','/containers/'+'d'*64+'/json'):return None
            return old(method,path,payload)
        self.b.docker=docker
        if record:
            with self.b.db() as con:
                con.execute('CREATE TABLE worker_retirement_intents(request_id TEXT PRIMARY KEY,container_id TEXT,name TEXT,state TEXT)')
                con.execute('INSERT INTO worker_retirement_intents VALUES(?,?,?,?)',(self.request,'d'*64,name,'gone'))

    def test_removed_worker_requires_exact_durable_retirement_not_only_absence(self):
        self.retired_worker(True)
        with patch.object(capture.validation_job,'run',side_effect=self.copied):
            self.assertEqual(self.call()['stage'],'awaiting_git_binding')

    def test_unexplained_worker_disappearance_is_not_completion_evidence(self):
        self.retired_worker(False)
        receipt=self.call()
        self.assertEqual(receipt['stage'],'technical_blocked');self.assertEqual(self.creates,0)

    def test_native_completion_without_successful_prompt_in_registered_session_is_rejected(self):
        with self.b.db() as con:
            con.execute("DELETE FROM acp_events WHERE request_id=? AND method='session/prompt'",(self.request,))
        receipt=self.call()
        self.assertEqual(receipt['stage'],'technical_blocked');self.assertEqual(self.creates,0)

    def test_sealed_maintenance_creates_no_volume_or_validation_job(self):
        with self.b.db() as con:
            con.execute('INSERT INTO controller_maintenance VALUES(?,?,?)',
                ('operator','sealed',json.dumps(dict(stage='sealed'))))
        with patch.object(capture.validation_job,'run') as job,self.assertRaises(capture.validation_job.Pending):self.call()
        job.assert_not_called();self.assertEqual(self.creates,0)

    def test_transient_native_api_failure_preserves_same_context_for_later_observation(self):
        with patch.object(capture.native,'task_record',side_effect=TimeoutError):
            with self.assertRaises(capture.validation_job.Pending):self.call()
        context,state=capture.load(self.b,self.request);deadline=state['deadline']
        with patch.object(capture.validation_job,'run',side_effect=self.copied):receipt=self.call()
        self.assertEqual(capture.load(self.b,self.request)[0],context)
        self.assertEqual(receipt['deadline'],deadline);self.assertEqual(self.creates,1)

    def test_failed_author_is_technical_incident_not_an_automatic_replacement(self):
        self.f.f.native['status']='failed';receipt=self.call()
        self.assertEqual(receipt['stage'],'technical_blocked')
        self.assertFalse(receipt['incident']['automatic_retry']);self.assertEqual(self.creates,0)


if __name__=='__main__':unittest.main()
