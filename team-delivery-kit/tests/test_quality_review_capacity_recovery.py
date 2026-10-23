"""Synthetic transport proofs never substitute for native review approval."""
import copy
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch,Mock
from broker import quality_review_capacity_recovery as capacity
from proxy_capacity_contract import digest,rejection


class QualityReviewCapacityEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.request='a0000000-0000-4000-8000-000000000001';self.operation='a0000000-0000-4000-8000-000000000002'
        self.namespace='delivery-kit-test';self.image='sha256:'+'7'*64;source=capacity.source_sha256()
        report=dict(operation='real_http_proxy_capacity_canary_v1',status='passed',source_sha256=source,
            max_request_bytes=2097152,accepted_request_bytes=[600086,2096726],fixed_forwards=2,
            oversized_rejected=True,call_ceiling_preserved=True,counter_preserved=True,fixture_max_calls=2,
            fixture_calls=2,model_calls=0,credentials_mounted=False,docker_socket=False,network='none',
            data_tmpfs=True,tests_approved=False,delivery_approval=False)
        proof=dict(operation='qualified_model_proxy_capacity_v1',namespace=self.namespace,
            maintenance_operation=self.operation,qualification_id='a0000000-0000-4000-8000-000000000003',
            proxy_image=self.image,source_sha256=source,script_sha256='1'*64,output_sha256='2'*64,
            max_request_bytes=2097152,report=report,container_retired=True,volumes_created=0,
            model_calls=0,tests_approved=False,delivery_approval=False)
        installed=dict(operation='model_proxy_capacity_install_v1',stage='installed_stopped',namespace=self.namespace,
            install_operation='a0000000-0000-4000-8000-000000000004',maintenance_operation=self.operation,
            qualification=proof,previous_container='8'*64,current_container='9'*64,
            previous_image='sha256:'+'6'*64,current_image=self.image,previous_capacity=524288,
            max_request_bytes=2097152,source_sha256=source,previous_source_sha256='3'*64,
            previous_logs_sha256='4'*64,counter=dict(calls=7,sha256='5'*64),max_calls=10000,
            data_mounts_preserved=True,credentials_mounts_preserved=True,other_containers_unchanged=True,
            maintenance_sealed=True,model_calls=0,delivery_approval=False)
        event=dict(event='model_proxy_request',status=400,category='request body size limit',call_number=None,
            route='/api/v1/chat/completions',execution_id=self.request,started_at=123.,duration_seconds=0.,response_deadline_seconds=120)
        self.transport=dict(operation='observed_proxy_capacity_change_v1',installation=installed,rejection=event)
        self.proxy=dict(Id='9'*64,Name='/'+self.namespace+'-model-proxy-1',Image=self.image,State=dict(Running=False),
            Config=dict(User='10000:10000',Labels={'com.docker.compose.project':self.namespace,'com.docker.compose.service':'model-proxy'},
                Env=['MODEL_PROXY_MAX_REQUEST_BYTES=2097152','MODEL_PROXY_MAX_CALLS=10000','MODEL_PROXY_COUNTER_PATH=/meter/calls.json']),
            HostConfig=dict(ReadonlyRootfs=True,Privileged=False),Mounts=[dict(Destination='/meter',RW=True),dict(Destination='/secret',RW=False)])
        def docker(method,path):
            self.assertEqual(method,'GET')
            if path=='/containers/'+self.namespace+'-model-proxy-1/json':return self.proxy
            if path=='/images/'+self.image+'/json':return dict(Id=self.image,Config=dict(User='10000:10000',Labels={'delivery-kit.component':'model-proxy'}))
            raise AssertionError('unexpected Docker operation')
        self.b=SimpleNamespace(PREFIX=self.namespace,docker=docker)

    def test_exact_installed_capacity_is_changed_evidence_not_a_review_approval(self):
        result=capacity.validate(self.b,self.transport,self.operation,self.request)
        self.assertEqual(len(result),64);self.assertFalse(self.transport['installation']['delivery_approval'])
        equivalent=copy.deepcopy(self.transport)
        equivalent['installation']['install_operation']='a0000000-0000-4000-8000-000000000005'
        self.assertEqual(capacity.validate(self.b,equivalent,self.operation,self.request),result)

    def test_unrelated_execution_or_non_capacity_failure_cannot_authorize_recovery(self):
        for change in (dict(status=502),dict(category='invalid_request'),dict(call_number=8),
                dict(execution_id='a0000000-0000-4000-8000-000000000006'),dict(started_at=float('inf'))):
            value=copy.deepcopy(self.transport);value['rejection'].update(change)
            with self.subTest(change=change),self.assertRaises(ValueError):capacity.validate(self.b,value,self.operation,self.request)

    def test_changed_budget_unqualified_source_mounts_or_same_capacity_fail_closed(self):
        for key,value in (('previous_capacity',2097152),('max_request_bytes',4194304),('source_sha256','0'*64),
                ('data_mounts_preserved',False),('credentials_mounts_preserved',False),('model_calls',1)):
            transport=copy.deepcopy(self.transport);transport['installation'][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):capacity.validate(self.b,transport,self.operation,self.request)
        self.proxy['Config']['Env'][1]='MODEL_PROXY_MAX_CALLS=99999'
        with self.assertRaises(ValueError):capacity.validate(self.b,self.transport,self.operation,self.request)

    def test_live_proxy_or_docker_socket_cannot_claim_sealed_disabled_recovery(self):
        self.proxy['State']['Running']=True
        with self.assertRaises(ValueError):capacity.validate(self.b,self.transport,self.operation,self.request)
        self.proxy['State']['Running']=False;self.proxy['Mounts'].append(dict(Destination='/var/run/docker.sock',RW=True))
        with self.assertRaises(ValueError):capacity.validate(self.b,self.transport,self.operation,self.request)


class QualityReviewCapacityLineageTests(unittest.TestCase):
    def setUp(self):
        import test_quality_review_completion_recovery as fixtures
        from broker import quality_review_attestation as attest,quality_review_completion_recovery as recovery
        self.recovery=recovery;self.attest=attest
        f=fixtures.QualityReviewCompletionRecoveryTests();self.f=f;original=attest.observe
        def failed_before_attestation(b,source):
            f.previous_task.update(status='failed',result=None,error='hermes session/prompt failed: Internal error',
                failure_reason='agent_error.provider_server_error')
            with b.db() as con:con.execute("UPDATE acp_events SET success=0 WHERE method='session/prompt'")
            return original(b,source)
        with patch.object(attest,'observe',side_effect=failed_before_attestation):f.setUp()
        self.addCleanup(f.doCleanups);self.b=f.b
        with self.b.db() as con:
            payload=json.loads(con.execute('SELECT payload FROM worker_creation_intents WHERE request_id=?',(f.request,)).fetchone()[0])
        f.worker=payload['Image'];self.b.QUALITY_WORKER_IMAGE=f.worker;self.b.QUALITY_REVIEW_WORKER_IMAGE=f.worker
        f.qualified['worker_image']=f.worker
        e=QualityReviewCapacityEvidenceTests();e.setUp();self.transport=copy.deepcopy(e.transport)
        self.transport['installation']['maintenance_operation']=f.operation
        self.transport['installation']['qualification']['maintenance_operation']=f.operation
        self.transport['rejection']['execution_id']=f.request
        previous=self.b.docker
        def docker(method,path,payload=None):
            if path=='/containers/'+self.b.PREFIX+'-model-proxy-1/json':return e.proxy
            if path=='/images/'+e.image+'/json':return e.b.docker(method,path)
            return previous(method,path,payload)
        self.b.docker=docker

    def register(self,**kwargs):
        f=self.f
        return self.recovery.register(self.b,f.source,f.previous_task['id'],f.operation,
            qualified=kwargs.get('qualified',f.qualified),installation=f.installation,
            transport=kwargs.get('transport',self.transport))

    def test_failed_transport_prepares_once_without_converting_its_attestation_or_reads(self):
        f=self.f;receipt=self.register();self.assertEqual(self.register(),receipt)
        self.assertEqual(receipt['diagnostic']['verdict_format'],'absent_due_to_transport')
        self.assertNotIn('native_output_sha256',receipt);self.assertIn('native_failure_sha256',receipt)
        self.assertFalse(receipt['incident_closed']);self.assertFalse(receipt['tests_approved'])
        self.assertEqual(self.attest.load(self.b,f.source,request_id=f.request),f.old)
        self.assertIsNone(self.attest.load(self.b,f.source))
        self.assertTrue(self.recovery.activation_ready(self.b,receipt['issue_id'],f.operation))
        with self.b.db() as con:self.assertEqual(con.execute('SELECT count(*) FROM grants').fetchone()[0],2)

    def test_a_failed_run_cannot_use_the_completed_review_adapter_without_capacity_evidence(self):
        with self.assertRaises(ValueError):self.f.register()
        bad=copy.deepcopy(self.transport);bad['rejection']['execution_id']=self.f.next_task
        with self.assertRaises(ValueError):self.register(transport=bad)

    def test_changed_historical_error_or_same_condition_cannot_trigger_another_retry(self):
        self.register();f=self.f
        q=copy.deepcopy(f.qualified);q['qualification_id']=f.next_task
        with self.assertRaises(ValueError):self.register(qualified=q)
        from broker import quality_test_review as review
        context,state=review.load(self.b,f.source);f.previous_task['error']='changed historical failure'
        with self.assertRaises(ValueError):self.recovery.exclude_completed(self.b,context,state,[f.previous_task])

    def test_fresh_successor_must_reacquire_reads_before_it_can_freeze_tests(self):
        from broker import quality_test_review as review,quality_review_launch as launch,acp_startup,read_stream_receipts
        f=self.f;self.register()
        with self.b.db() as con:con.execute('DELETE FROM controller_maintenance')
        with patch.object(review.native,'ensure_review_start',return_value=f.wakeup):review.dispatch(self.b,f.source)
        context,state=review.load(self.b,f.source)
        current={**f.previous_task,'id':f.next_task,'status':'running','result':None,'error':None,'failure_reason':None,
            'wakeup_id':state['wakeup_id'],'handoff_note':review.note(self.b,context,state)}
        records={r['id']:r for r in (f.f.f.f.capture.native,f.previous_task,current)}
        p=patch.object(self.recovery.native,'task_record',side_effect=lambda settings,t,a:records[t]);p.start();self.addCleanup(p.stop)
        p=patch.object(self.recovery.native,'issue_task_runs',side_effect=lambda *_:list(records.values()));p.start();self.addCleanup(p.stop)
        grant=review.admit(self.b,f.source,current['id'],current['agent_id']);request=grant['request_id']
        self.assertNotEqual(request,f.request)
        with self.b.db() as con:self.assertEqual(read_stream_receipts.load(con,current['id']),[])
        launch.execute(self.b,grant['capability'],{},True,True)
        with self.b.db() as con:
            row=dict(con.execute('SELECT * FROM grants WHERE request_id=?',(request,)).fetchone())
            binding=dict(con.execute('SELECT * FROM native_bindings WHERE request_id=?',(request,)).fetchone())
        result=acp_startup.advance_worker(self.b,row,binding)
        with self.b.db() as con:con.execute('INSERT INTO acp_startups VALUES(?,?)',(request,json.dumps(dict(stage='transport_intent'))))
        with patch('broker.acp_transport.Transport',return_value=Mock()):launch.open_transport(self.b,row,result,binding['scope'])
        with self.b.db() as con:
            con.execute('INSERT INTO acp_sessions VALUES(?,?)',(binding['scope'],'capacity-successor'))
            for method in ('initialize','session/new','session/prompt'):
                con.execute('INSERT INTO acp_events VALUES(?,?,?,?)',(request,method,'capacity-successor',1))
            con.execute("UPDATE leases SET status='closed' WHERE request_id=?",(request,))
            read_stream_receipts.store(con,binding,f.f.pages,'review')
        current.update(status='completed',result=dict(output=json.dumps(f.f.verdict)))
        receipt=self.attest.observe(self.b,f.source)
        self.assertEqual(receipt['stage'],'tests_frozen');self.assertEqual(receipt['request_id'],request)
        self.assertEqual(self.attest.load(self.b,f.source,request_id=f.request),f.old)
        from broker import quality_implementation_admission as implementation
        bound,_=implementation.register(self.b,f.source)
        self.assertEqual(bound['frozen_sha256'],review.quality.digest(receipt))


if __name__=='__main__':unittest.main()
