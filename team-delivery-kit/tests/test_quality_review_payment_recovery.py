"""Synthetic native/DB fixtures: never provider credit or real approval evidence."""
import copy
import json
import time
import unittest
from unittest.mock import patch,Mock
from broker import quality_review_payment_recovery as payment
from broker import quality_review_completion_recovery as recovery,quality_review_attestation as attest
import test_quality_review_completion_recovery as fixtures
from test_quality_provider_resolution import facts


class QualityReviewPaymentRecoveryTests(unittest.TestCase):
    def setUp(self):
        f=fixtures.QualityReviewCompletionRecoveryTests();self.f=f;original=attest.observe
        def failed(b,source):
            f.previous_task.update(status='failed',result=None,error='hermes session/prompt failed: Internal error',
                failure_reason='agent_error.provider_server_error')
            with b.db() as con:con.execute("UPDATE acp_events SET success=0 WHERE method='session/prompt'")
            return original(b,source)
        with patch.object(attest,'observe',side_effect=failed):f.setUp()
        self.addCleanup(f.doCleanups);self.b=f.b
        with self.b.db() as con:
            payload=json.loads(con.execute('SELECT payload FROM worker_creation_intents WHERE request_id=?',(f.request,)).fetchone()[0])
        f.worker=payload['Image'];self.b.QUALITY_WORKER_IMAGE=f.worker;self.b.QUALITY_REVIEW_WORKER_IMAGE=f.worker
        f.qualified['worker_image']=f.worker
        self.proof=facts();self.proof.update(namespace=self.b.PREFIX,maintenance_operation=f.operation,request_id=f.request,
            proxy_source_sha256=payment.source_sha256())
        self.proof['event'].update(execution_id=f.request,started_at=time.time()-5)
        self.proof['resolution'].update(operation_id=f.operation,resolved_at=time.time())
        self.runtime=dict(image=f.installation['current_image'],container_id=f.installation['current_container'])
        self.proxy=dict(Id=self.proof['proxy_container'],Name='/'+self.b.PREFIX+'-model-proxy-1',
            Image=self.proof['proxy_image'],State=dict(Running=False),Config=dict(User='10000:10000',
                Labels={'com.docker.compose.project':self.b.PREFIX,'com.docker.compose.service':'model-proxy'},
                Env=['MODEL_PROXY_MAX_CALLS=10000','MODEL_PROXY_MAX_REQUEST_BYTES=2097152','MODEL_PROXY_COUNTER_PATH=/meter/calls.json']),
            HostConfig=dict(ReadonlyRootfs=True,Privileged=False),
            Mounts=[dict(Destination='/meter',RW=True),dict(Destination='/secret',RW=False)])
        original_docker=self.b.docker
        def docker(method,path,payload=None):
            if path=='/containers/'+self.b.PREFIX+'-model-proxy-1/json':return self.proxy
            if path=='/images/'+self.proof['proxy_image']+'/json':
                return dict(Id=self.proof['proxy_image'],Config=dict(User='10000:10000',Labels={'delivery-kit.component':'model-proxy'}))
            return original_docker(method,path,payload)
        self.b.docker=docker

    def register(self,**kwargs):
        f=self.f
        return recovery.register(self.b,f.source,f.previous_task['id'],f.operation,qualified=f.qualified,
            runtime_identity=kwargs.get('runtime_identity',self.runtime),provider_resolution=kwargs.get('provider_resolution',self.proof))

    def test_complete_failed_review_can_prepare_once_after_exact_financial_resolution(self):
        f=self.f;receipt=self.register();self.assertEqual(self.register(),receipt)
        self.assertEqual(receipt['previous_attestation'],f.old)
        self.assertEqual(receipt['diagnostic']['reads']['complete_files'],4)
        self.assertEqual(receipt['diagnostic']['verdict_format'],'absent_due_to_payment_failure')
        self.assertFalse(receipt['tests_approved']);self.assertFalse(receipt['incident_closed'])
        self.assertIn('native_failure_sha256',receipt)
        self.assertTrue(recovery.activation_ready(self.b,receipt['issue_id'],f.operation))
        with self.b.db() as con:
            self.assertEqual(con.execute('SELECT count(*) FROM grants').fetchone()[0],2)
            self.assertEqual(con.execute('SELECT count(*) FROM quality_review_successor_admissions').fetchone()[0],0)
        self.assertEqual(attest.load(self.b,f.source,request_id=f.request),f.old)
        self.assertIsNone(attest.load(self.b,f.source))

    def test_other_failure_routes_cannot_borrow_payment_evidence(self):
        f=self.f
        with self.assertRaises(ValueError):f.register()
        with self.assertRaises(ValueError):recovery.register(self.b,f.source,f.previous_task['id'],f.operation,
            qualified=f.qualified,installation=f.installation,provider_resolution=self.proof,runtime_identity=self.runtime)
        with self.assertRaises(ValueError):recovery.register(self.b,f.source,f.previous_task['id'],f.operation,
            qualified=f.qualified,provider_resolution=self.proof,runtime_identity=self.runtime,failed_review=True)

    def test_no_ack_wrong_request_or_changed_counter_cannot_resume(self):
        for key,value in (('operator_confirmed',False),('request_id',self.f.next_task),('pause_absent',False)):
            with self.subTest(key=key),self.assertRaises(ValueError):self.register(provider_resolution={**self.proof,key:value})
        changed=copy.deepcopy(self.proof);changed['counter']['calls']=18
        with self.assertRaises(ValueError):self.register(provider_resolution=changed)

    def test_live_proxy_foreign_controller_or_unretired_worker_stays_blocked(self):
        self.proxy['State']['Running']=True
        with self.assertRaises(ValueError):self.register()
        self.proxy['State']['Running']=False
        with self.assertRaises(ValueError):self.register(runtime_identity={**self.runtime,'container_id':'0'*64})
        with self.b.db() as con:con.execute("UPDATE worker_retirement_intents SET state='delete_outcome_unknown'")
        with self.assertRaises(ValueError):self.register()

    def test_same_payment_cannot_rearm_by_another_receipt_identity(self):
        self.register();proof=copy.deepcopy(self.proof)
        proof['resolution']['resolved_at']+=.01
        with self.assertRaises(ValueError):self.register(provider_resolution=proof)
        context,state=recovery.review.load(self.b,self.f.source)
        self.f.previous_task['error']='changed historical provider error'
        with self.assertRaises(ValueError):recovery.exclude_completed(self.b,context,state,[self.f.previous_task])

    def successor(self,with_reads):
        from broker import quality_test_review as review,quality_review_launch as launch,acp_startup,read_stream_receipts
        f=self.f;self.register()
        with self.b.db() as con:con.execute('DELETE FROM controller_maintenance')
        with patch.object(review.native,'ensure_review_start',return_value=f.wakeup):review.dispatch(self.b,f.source)
        context,state=review.load(self.b,f.source)
        current={**f.previous_task,'id':f.next_task,'status':'running','result':None,'error':None,'failure_reason':None,
            'wakeup_id':state['wakeup_id'],'handoff_note':review.note(self.b,context,state)}
        records={r['id']:r for r in (f.f.f.f.capture.native,f.previous_task,current)}
        for target in (patch.object(recovery.native,'task_record',side_effect=lambda settings,t,a:records[t]),
                patch.object(recovery.native,'issue_task_runs',side_effect=lambda *_:list(records.values()))):
            target.start();self.addCleanup(target.stop)
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
            con.execute('INSERT INTO acp_sessions VALUES(?,?)',(binding['scope'],'payment-successor'))
            for method in ('initialize','session/new','session/prompt'):
                con.execute('INSERT INTO acp_events VALUES(?,?,?,?)',(request,method,'payment-successor',1))
            con.execute("UPDATE leases SET status='closed' WHERE request_id=?",(request,))
            if with_reads:read_stream_receipts.store(con,binding,f.f.pages,'review')
        current.update(status='completed',result=dict(output=json.dumps(f.f.verdict)))
        return request,attest.observe(self.b,f.source)

    def test_payment_resolution_never_transfers_reads_from_failed_review(self):
        request,receipt=self.successor(False)
        self.assertEqual(receipt['stage'],'technical_blocked')
        self.assertEqual(receipt['incident']['category'],'complete_snapshot_reads')
        self.assertEqual(receipt['incident']['completion_diagnostic']['reads']['complete_files'],0)
        self.assertFalse(receipt['tests_approved']);self.assertEqual(receipt['request_id'],request)
        self.assertEqual(attest.load(self.b,self.f.source,request_id=self.f.request),self.f.old)

    def test_fresh_independent_reads_and_verdict_can_freeze_exact_tests_without_old_approval(self):
        request,receipt=self.successor(True)
        self.assertEqual(receipt['stage'],'tests_frozen');self.assertEqual(receipt['request_id'],request)
        self.assertFalse(receipt['execution_authorized']);self.assertFalse(receipt['delivery_approval'])
        self.assertEqual(attest.load(self.b,self.f.source,request_id=self.f.request),self.f.old)


if __name__=='__main__':unittest.main()
