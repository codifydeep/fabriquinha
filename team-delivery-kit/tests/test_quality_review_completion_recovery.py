"""Changed-condition controller fixtures; not native qualification/approval."""
import copy
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch,Mock
from broker import quality_review_completion_recovery as recovery,quality_team_progress as team
from broker import quality_test_review as review,quality_review_attestation as attest,quality_review_launch as launch
import test_quality_review_attestation as fixtures
import test_quality_team_progress as team_fixtures
from test_review_execution_evidence import evidence as execution_evidence
from test_review_execution_evidence import scale_evidence


class QualityReviewCompletionRecoveryTests(unittest.TestCase):
    def setUp(self):
        f=fixtures.QualityReviewAttestationTests();f.setUp();self.addCleanup(f.doCleanups)
        self.f=f;self.b=f.b;team_fixtures.configured(self.b)
        self.source=f.source;self.previous_task=f.f.record;self.request=f.request
        self.previous_task['result']['output']='Prose before verdict\n'+json.dumps(f.verdict)
        self.old=attest.observe(self.b,self.source)
        self.operation='a0000000-0000-4000-8000-000000000001'
        self.next_task='a0000000-0000-4000-8000-000000000002'
        self.wakeup=dict(id='a0000000-0000-4000-8000-000000000003',issue_id=self.previous_task['issue_id'],agent_id=self.previous_task['agent_id'])
        self.installation=dict(install_operation='a0000000-0000-4000-8000-000000000004',previous_image='sha256:'+'0'*64,
            current_image='sha256:'+'a'*64,previous_container='c'*64,current_container='f'*64)
        self.worker='sha256:'+'e'*64
        self.b.QUALITY_WORKER_IMAGE=self.worker;self.b.QUALITY_REVIEW_WORKER_IMAGE=self.worker
        guards={k:hashlib.sha256(Path(m.__file__).read_bytes()).hexdigest() for k,m in
            dict(feedback=recovery.stop,phase=recovery.phase,verdict=recovery.verdict,installer=recovery.installer,paging=recovery.paging).items()}
        guards['handler']=hashlib.sha256(Path(recovery.__file__).with_name('review_tool_policy.py').read_bytes()).hexdigest()
        report=dict(operation='real_hermes_review_stop_loop_canary_v1',status='passed',provider='fixed_loopback_not_model',
            total_fixed_provider_calls=24,execution_controls=execution_evidence(),scale_controls=scale_evidence(),
            fixture_source_sha256=hashlib.sha256(Path(recovery.execution_evidence.__file__).read_bytes()).hexdigest(),
            model_calls=0,fixed_provider_calls=3,feedback_rounds=1,max_iterations=40,acp=True,same_agent=True,
            protected_files_unchanged=True,tests_approved=False,delivery_approval=False,
            guard_sources={**guards,'loop':'1'*64,'acp':'2'*64,'session':'3'*64})
        self.qualified=dict(operation='qualified_review_stop_worker_v1',namespace=self.b.PREFIX,
            maintenance_operation=self.operation,qualification_id='a0000000-0000-4000-8000-000000000005',
            worker_image=self.worker,guards=guards,report=report,container_retired=True,model_calls=0,
            tests_approved=False,delivery_approval=False)
        docker=self.b.docker
        def installed(method,path,payload=None):
            if path=='/containers/'+self.b.PREFIX+'-execution-broker-1/json':
                return dict(Id='f'*64,Image=self.installation['current_image'],State=dict(Running=True),
                    Config=dict(Labels={'com.docker.compose.project':self.b.PREFIX,'com.docker.compose.service':'execution-broker'}))
            if path=='/images/'+self.worker+'/json':
                return dict(Id=self.worker,Config=dict(User='10000:10000',Volumes=None,Labels={
                    'delivery-kit.component':'quality-author-worker'}))
            return docker(method,path,payload)
        self.b.docker=installed
        with self.b.db() as con:
            team.initialize(con)
            con.execute('CREATE TABLE worker_retirement_intents(request_id TEXT PRIMARY KEY,container_id TEXT,name TEXT,state TEXT)')
            con.execute('INSERT INTO worker_retirement_intents VALUES(?,?,?,?)',
                (self.request,'d'*64,self.b.PREFIX+'-job-'+self.request,'gone'))
        identity,state=team.register(self.b,self.source)
        team.save(self.b,self.source,identity,state,team.blocked(identity,self.old,review_problem=True))
        with self.b.db() as con:
            held=dict(stage='sealed',drained=True,namespace=self.b.PREFIX,operation_id=self.operation)
            con.execute('INSERT INTO controller_maintenance VALUES(?,?,?)',(self.operation,'sealed',json.dumps(held)))
        self.b.SESSIONS.clear();self.f.f.worker=None
        p=patch.object(recovery.maintenance,'native_active',return_value=[]);p.start();self.addCleanup(p.stop)

    def register(self,**kwargs):
        return recovery.register(self.b,self.source,self.previous_task['id'],self.operation,
            qualified=kwargs.get('qualified',self.qualified),installation=kwargs.get('installation',self.installation))

    def resumed(self):
        receipt=self.register()
        with self.b.db() as con:con.execute('DELETE FROM controller_maintenance')
        with patch.object(review.native,'ensure_review_start',return_value=self.wakeup):review.dispatch(self.b,self.source)
        context,state=review.load(self.b,self.source)
        current={**self.previous_task,'id':self.next_task,'status':'running','wakeup_id':state['wakeup_id'],
            'handoff_note':review.note(self.b,context,state),'result':None}
        author=self.f.f.f.capture.native
        self.native_records={r['id']:r for r in (author,self.previous_task,current)}
        p=patch.object(recovery.native,'task_record',side_effect=lambda settings,t,a:self.native_records[t]);p.start();self.addCleanup(p.stop)
        p=patch.object(recovery.native,'issue_task_runs',side_effect=lambda *_:list(self.native_records.values()));p.start();self.addCleanup(p.stop)
        grant=review.admit(self.b,self.source,self.next_task,current['agent_id'])
        return receipt,grant,current

    def test_prepares_once_without_reinterpreting_old_verdict_or_replaying_grant(self):
        receipt=self.register();self.assertEqual(self.register(),receipt)
        self.assertEqual(receipt['previous_attestation'],self.old)
        self.assertEqual(receipt['diagnostic']['verdict_format'],'invalid')
        self.assertEqual(attest.load(self.b,self.source,request_id=self.request),self.old)
        self.assertIsNone(attest.load(self.b,self.source));self.assertIsNone(attest.status(self.b,self.source))
        self.assertFalse(receipt['incident_closed']);self.assertFalse(receipt['tests_approved'])
        self.assertTrue(recovery.activation_ready(self.b,receipt['issue_id'],self.operation))
        with self.b.db() as con:
            self.assertEqual(con.execute('SELECT count(*) FROM grants').fetchone()[0],2)
            self.assertEqual(con.execute('SELECT count(*) FROM quality_review_successor_admissions').fetchone()[0],0)
            self.assertEqual(con.execute('SELECT request_id FROM quality_review_attestations').fetchone()[0],self.request)

    def test_successor_is_admitted_to_a_new_record_and_old_capability_is_fenced(self):
        receipt,grant,current=self.resumed()
        self.assertNotEqual(grant['request_id'],self.request)
        self.assertEqual(launch.current(self.b,grant['request_id'])['task_id'],self.next_task)
        self.assertTrue(launch.owns(self.b,grant['request_id']))
        with self.b.db() as con:
            self.assertEqual(con.execute('SELECT task_id FROM quality_review_admissions').fetchone()[0],self.previous_task['id'])
            self.assertEqual(con.execute('SELECT task_id FROM quality_review_successor_admissions').fetchone()[0],self.next_task)
            with self.assertRaises(ValueError):review.admission(con,self.request)
        with self.assertRaises(ValueError):review.admit(self.b,self.source,self.next_task,current['agent_id'])

    def test_same_condition_cannot_be_replayed_with_another_task_or_qualification_id(self):
        self.register()
        q=copy.deepcopy(self.qualified);q['qualification_id']='a0000000-0000-4000-8000-000000000006'
        with self.assertRaises(ValueError):recovery.register(self.b,self.source,self.next_task,self.operation,qualified=q,installation=self.installation)
        with self.assertRaises(ValueError):self.register(qualified=q)

    def test_unqualified_worker_stale_code_or_same_controller_cannot_claim_a_change(self):
        q=copy.deepcopy(self.qualified);q['guards']['feedback']='0'*64
        with self.assertRaises(ValueError):self.register(qualified=q)
        q=copy.deepcopy(self.qualified);q['report']['acp']=False
        with self.assertRaises(ValueError):self.register(qualified=q)
        q=copy.deepcopy(self.qualified);q['worker_image']='sha256:'+'b'*64
        with self.assertRaises(ValueError):self.register(qualified=q)
        with self.assertRaises(ValueError):self.register(installation={**self.installation,'current_image':self.installation['previous_image']})

    def test_new_paging_dependency_must_be_qualified_at_its_exact_installed_hash(self):
        q=copy.deepcopy(self.qualified)
        q['guards'].pop('paging',None)
        q['report']['guard_sources'].pop('paging',None)
        with self.assertRaises(ValueError):self.register(qualified=q)

    def test_unretired_or_running_previous_worker_cannot_free_capacity_by_declaration(self):
        with self.b.db() as con:con.execute("UPDATE worker_retirement_intents SET state='delete_outcome_unknown'")
        with self.assertRaises(ValueError):self.register()
        with self.b.db() as con:con.execute("UPDATE worker_retirement_intents SET state='gone'")
        self.f.f.worker=dict(Id='d'*64)
        with self.assertRaises(ValueError):self.register()

    def test_changed_old_native_output_or_attestation_breaks_historical_exclusion(self):
        self.register()
        context,state=review.load(self.b,self.source)
        self.previous_task['result']['output']='changed'
        with self.assertRaises(ValueError):recovery.exclude_completed(self.b,context,state,[self.previous_task])

    def test_unknown_extra_native_review_is_not_hidden_by_recovery(self):
        extra={**self.previous_task,'id':self.next_task}
        with patch.object(recovery.native,'issue_task_runs',return_value=[self.previous_task,extra]):
            with self.assertRaises(ValueError):self.register()

    def test_valid_successor_can_freeze_exact_snapshot_without_overwriting_old_failure(self):
        from broker import acp_startup,read_stream_receipts
        _,grant,record=self.resumed();request=grant['request_id']
        launch.execute(self.b,grant['capability'],{},True,True)
        with self.b.db() as con:
            row=dict(con.execute('SELECT * FROM grants WHERE request_id=?',(request,)).fetchone())
            binding=dict(con.execute('SELECT * FROM native_bindings WHERE request_id=?',(request,)).fetchone())
        result=acp_startup.advance_worker(self.b,row,binding)
        with self.b.db() as con:
            con.execute('INSERT INTO acp_startups VALUES(?,?)',(request,json.dumps(dict(stage='transport_intent'))))
        with patch('broker.acp_transport.Transport',return_value=Mock()):launch.open_transport(self.b,row,result,binding['scope'])
        with self.b.db() as con:
            con.execute('INSERT INTO acp_sessions VALUES(?,?)',(binding['scope'],'successor-session'))
            for method in ('initialize','session/new','session/prompt'):
                con.execute('INSERT INTO acp_events VALUES(?,?,?,?)',(request,method,'successor-session',1))
            con.execute("UPDATE leases SET status='closed' WHERE request_id=?",(request,))
            read_stream_receipts.store(con,binding,self.f.pages,'review')
        record.update(status='completed',result=dict(output=json.dumps(self.f.verdict)))
        receipt=attest.observe(self.b,self.source)
        self.assertEqual(receipt['stage'],'tests_frozen');self.assertEqual(receipt['request_id'],request)
        self.assertEqual(attest.load(self.b,self.source,request_id=self.request),self.old)
        with self.b.db() as con:
            self.assertEqual(con.execute('SELECT count(*) FROM quality_review_successor_attestations').fetchone()[0],1)
            self.assertEqual(con.execute('SELECT count(*) FROM quality_review_attestations').fetchone()[0],1)
        from broker import quality_implementation_admission as implementation
        context,_=implementation.register(self.b,self.source)
        task='b0000000-0000-4000-8000-000000000005'
        wake=dict(id='b0000000-0000-4000-8000-000000000006',agent_id=context['author'],issue_id=context['issue_id'])
        with patch.object(recovery.native,'ensure_scope_author_start',return_value=wake):implementation.dispatch(self.b,self.source)
        self.native_records[task]=dict(id=task,agent_id=context['author'],issue_id=context['issue_id'],status='running',
            created_at='2026-10-23T20:00:00Z',workspace_id=self.previous_task['workspace_id'],
            runtime_id=self.previous_task['runtime_id'],wakeup_id=wake['id'],
            handoff_note='DELIVERY_SCOPE_AUTHOR_START '+context['marker']+'\nSource: '+context['origin']+'\n'+context['instruction'])
        product=implementation.admit(self.b,self.source,task,context['author'])
        with self.b.db() as con:bound=implementation.load(con,product['request_id'])
        self.assertEqual(bound['frozen_sha256'],review.quality.digest(receipt))
        self.assertNotEqual(bound['frozen_sha256'],review.quality.digest(self.old))

    def test_completion_recovery_coexists_with_a_prior_zero_acp_bootstrap_recovery(self):
        from test_quality_review_bootstrap_recovery import BootstrapRecoveryTests
        from broker import acp_startup,read_stream_receipts
        boot=BootstrapRecoveryTests();boot.setUp();self.addCleanup(boot.doCleanups)
        _,grant,record=boot.resumed();b=boot.b;request=grant['request_id'];source=boot.source
        launch.execute(b,grant['capability'],{},True,True)
        with b.db() as con:
            row=dict(con.execute('SELECT * FROM grants WHERE request_id=?',(request,)).fetchone())
            binding=dict(con.execute('SELECT * FROM native_bindings WHERE request_id=?',(request,)).fetchone())
        result=acp_startup.advance_worker(b,row,binding)
        with b.db() as con:con.execute('INSERT INTO acp_startups VALUES(?,?)',(request,json.dumps(dict(stage='transport_intent'))))
        with patch('broker.acp_transport.Transport',return_value=Mock()):launch.open_transport(b,row,result,binding['scope'])
        with b.db() as con:
            con.execute('INSERT INTO acp_sessions VALUES(?,?)',(binding['scope'],'review-session'))
            for method in ('initialize','session/new','session/prompt'):
                con.execute('INSERT INTO acp_events VALUES(?,?,?,?)',(request,method,'review-session',1))
            con.execute("UPDATE leases SET status='closed' WHERE request_id=?",(request,))
            read_stream_receipts.store(con,binding,boot.f.pages,'review')
            con.execute('CREATE TABLE worker_retirement_intents(request_id TEXT PRIMARY KEY,container_id TEXT,name TEXT,state TEXT)')
            con.execute('INSERT INTO worker_retirement_intents VALUES(?,?,?,?)',(request,'d'*64,b.PREFIX+'-job-'+request,'gone'))
        record.update(status='completed',result=dict(output='Prose\n'+json.dumps(boot.f.verdict)))
        old=attest.observe(b,source);identity,state=team.load(b,source)
        team.save(b,source,identity,state,team.blocked(identity,old,review_problem=True))
        with b.db() as con:
            held=dict(stage='sealed',drained=True,operation_id=self.operation,namespace=b.PREFIX)
            con.execute('INSERT INTO controller_maintenance VALUES(?,?,?)',(self.operation,'sealed',json.dumps(held)))
        b.SESSIONS.clear();boot.f.f.worker=None
        b.QUALITY_WORKER_IMAGE=self.worker;b.QUALITY_REVIEW_WORKER_IMAGE=self.worker
        docker=b.docker
        def installed(method,path,payload=None):
            if path=='/containers/'+b.PREFIX+'-execution-broker-1/json':
                return dict(Id='f'*64,Image=self.installation['current_image'],State=dict(Running=True),
                    Config=dict(Labels={'com.docker.compose.project':b.PREFIX,'com.docker.compose.service':'execution-broker'}))
            if path=='/images/'+self.worker+'/json':return dict(Id=self.worker,Config=dict(User='10000:10000',Volumes=None,Labels={'delivery-kit.component':'quality-author-worker'}))
            return docker(method,path,payload)
        b.docker=installed
        receipt=recovery.register(b,source,record['id'],self.operation,qualified=self.qualified,installation=self.installation)
        self.assertEqual(receipt['previous_request'],request)
        self.assertEqual(attest.load(b,source,request_id=boot.request),boot.old_attestation)
        self.assertEqual(attest.load(b,source,request_id=request),old)
        self.assertTrue(recovery.activation_ready(b,receipt['issue_id'],self.operation))
        context,state=review.load(b,source)
        self.assertEqual(review.eligible_runs(b,context,state,list(boot.native_records.values())),[boot.f.f.f.capture.native])


if __name__=='__main__':unittest.main()
