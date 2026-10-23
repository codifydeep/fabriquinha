"""Versioned zero-ACP recovery fixtures, never native reviewer approval."""
import hashlib
import json
from contextlib import contextmanager
from pathlib import Path
import unittest
from unittest.mock import patch,Mock
from broker import quality_review_bootstrap_recovery as recovery,quality_team_progress as team
from broker import quality_test_review as review,quality_review_attestation as attestation,quality_review_launch as launch
import test_quality_review_attestation as fixtures
import test_quality_team_progress as team_fixtures


class BootstrapRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.QualityReviewAttestationTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.b=self.f.b;team_fixtures.configured(self.b)
        self.b.STATE=self.b.STATE.resolve()
        self.installation=dict(install_operation='a0000000-0000-4000-8000-000000000004',previous_image=recovery.OLD_CONTROLLER_IMAGE,
            current_image='sha256:'+'e'*64,previous_container='c'*64,current_container='f'*64)
        docker=self.b.docker
        def installed(method,path,payload=None):
            if path=='/containers/'+self.b.PREFIX+'-execution-broker-1/json':
                return dict(Id='f'*64,Image=self.installation['current_image'],State=dict(Running=True),
                    Config=dict(Labels={'com.docker.compose.project':self.b.PREFIX,'com.docker.compose.service':'execution-broker'}))
            return docker(method,path,payload)
        self.b.docker=installed
        self.source=self.f.source;self.old_task=self.f.f.record
        self.old_task.update(status='failed',result=None)
        self.request=self.f.request;self.failed=self.old_task['id'];self.old_attestation=self.f.call()
        self.operation='a0000000-0000-4000-8000-000000000001'
        self.next_task='a0000000-0000-4000-8000-000000000002'
        self.wakeup=dict(id='a0000000-0000-4000-8000-000000000003',issue_id=self.old_task['issue_id'],agent_id=self.old_task['agent_id'])
        self.guard=hashlib.sha256(Path(recovery.intents.__file__).read_bytes()).hexdigest()
        with self.b.db() as con:team.initialize(con)
        identity,state=team.register(self.b,self.source)
        team.save(self.b,self.source,identity,state,team.blocked(identity,self.old_attestation,review_problem=True))
        with self.b.db() as con:
            con.execute("UPDATE leases SET status='failed' WHERE request_id=?",(self.request,))
            con.execute('DELETE FROM acp_events');con.execute('DELETE FROM acp_sessions')
            con.execute('DELETE FROM quality_transport_intents');con.execute('DELETE FROM observed_read_stream')
            con.execute('INSERT OR REPLACE INTO acp_startups VALUES(?,?)',(self.request,json.dumps(dict(stage='failed',category='startup_broker_internal'))))
            held=dict(stage='sealed',drained=True,operation_id=self.operation,namespace=self.b.PREFIX)
            con.execute('INSERT INTO controller_maintenance VALUES(?,?,?)',(self.operation,'sealed',json.dumps(held)))
        self.b.SESSIONS.clear();self.f.f.worker=None
        root=self.b.STATE/'helper-archives'/('d'*64);root.mkdir(mode=0o700,parents=True)
        metadata=dict(container_id='d'*64,owner=self.b.OWNER,name=self.b.PREFIX+'-job-'+self.request,
            identity_key='delivery-kit.request',identity_value=self.request,logs_sha256=hashlib.sha256(b'').hexdigest())
        for name,raw in [('metadata.json',json.dumps(metadata).encode()),('logs.txt',b'')]:
            path=root/name;path.write_bytes(raw);path.chmod(0o600)
        for name,value in [('task_messages',[]),('native_active',[])]:
            target=recovery.native if name=='task_messages' else recovery.maintenance
            p=patch.object(target,name,return_value=value);p.start();self.addCleanup(p.stop)

    def register(self):return recovery.register(self.b,self.source,self.failed,self.guard,self.operation,installation=self.installation)

    def resumed(self):
        receipt=self.register()
        with self.b.db() as con:con.execute('DELETE FROM controller_maintenance')
        with patch.object(review.native,'ensure_review_start',return_value=self.wakeup):review.dispatch(self.b,self.source)
        c,s=review.load(self.b,self.source)
        record={**self.old_task,'id':self.next_task,'status':'running','wakeup_id':s['wakeup_id'],
            'handoff_note':review.note(self.b,c,s)}
        source=self.f.f.f.capture.native
        records={r['id']:r for r in [source,self.old_task,record]}
        self.native_records=records
        p=patch.object(recovery.native,'task_record',side_effect=lambda settings,t,a:records[t]);p.start();self.addCleanup(p.stop)
        p=patch.object(recovery.native,'issue_task_runs',side_effect=lambda *_:list(records.values()));p.start();self.addCleanup(p.stop)
        grant=review.admit(self.b,self.source,self.next_task,self.old_task['agent_id'])
        return receipt,grant,record

    def test_preserves_old_execution_and_attestation_and_is_idempotent(self):
        receipt=self.register();self.assertEqual(self.register(),receipt)
        self.assertEqual(receipt['previous_attestation'],self.old_attestation)
        self.assertEqual(attestation.load(self.b,self.source,request_id=self.request),self.old_attestation)
        self.assertIsNone(attestation.load(self.b,self.source))
        self.assertIsNone(attestation.status(self.b,self.source))
        self.assertEqual(review.load(self.b,self.source)[1]['stage'],'prepared')
        with self.b.db() as con:
            self.assertEqual(con.execute('SELECT count(*) FROM quality_review_admissions').fetchone()[0],1)
            self.assertEqual(con.execute('SELECT count(*) FROM quality_review_attempts').fetchone()[0],0)
        self.assertFalse(receipt['tests_approved']);self.assertFalse(receipt['delivery_approval'])
        self.assertTrue(recovery.activation_ready(self.b,receipt['issue_id'],self.operation))
        with self.assertRaises(ValueError):recovery.activation_ready(self.b,receipt['issue_id'],self.source)

    def test_same_controller_or_unverified_install_identity_cannot_claim_a_change(self):
        bad={**self.installation,'current_image':recovery.OLD_CONTROLLER_IMAGE}
        with self.assertRaises(ValueError):recovery.register(self.b,self.source,self.failed,self.guard,self.operation,installation=bad)
        bad={**self.installation,'current_container':'0'*64}
        with self.assertRaises(ValueError):recovery.register(self.b,self.source,self.failed,self.guard,self.operation,installation=bad)

    def test_new_review_uses_new_capability_and_old_admission_is_not_overwritten(self):
        receipt,grant,record=self.resumed()
        self.assertNotEqual(grant['request_id'],self.request)
        self.assertEqual(launch.current(self.b,grant['request_id'])['task_id'],self.next_task)
        self.assertTrue(launch.owns(self.b,grant['request_id']))
        with self.b.db() as con:
            self.assertEqual(review.admission(con,grant['request_id'])['phase'],'test_review_v2')
            self.assertEqual(con.execute('SELECT task_id FROM quality_review_admissions').fetchone()[0],self.failed)
            with self.assertRaises(ValueError):review.admission(con,self.request)
        with self.assertRaises(ValueError):review.admit(self.b,self.source,self.next_task,record['agent_id'])
        self.assertEqual(self.register(),receipt)
        with self.assertRaises(ValueError):recovery.register(self.b,self.source,self.next_task,self.guard,self.operation,installation=self.installation)

    def test_old_guard_any_acp_or_transport_and_unretired_worker_are_rejected(self):
        with self.assertRaises(ValueError):recovery.register(self.b,self.source,self.failed,recovery.OLD_GUARD_SHA,self.operation,installation=self.installation)
        with self.b.db() as con:con.execute('INSERT INTO acp_events VALUES(?,?,?,?)',(self.request,'initialize','old',1))
        with self.assertRaises(ValueError):self.register()
        with self.b.db() as con:
            con.execute('DELETE FROM acp_events');con.execute('INSERT INTO quality_transport_intents VALUES(?,?)',(self.request,'opening'))
        with self.assertRaises(ValueError):self.register()
        with self.b.db() as con:con.execute('DELETE FROM quality_transport_intents')
        self.f.f.worker=dict(Id='d'*64)
        with self.assertRaises(ValueError):self.register()

    def test_archive_corruption_or_tool_read_evidence_cannot_be_declared_zero_acp(self):
        path=self.b.STATE/'helper-archives'/('d'*64)/'logs.txt';path.write_bytes(b'changed')
        with self.assertRaises(ValueError):self.register()
        path.write_bytes(b'')
        with self.b.db() as con:con.execute('INSERT INTO observed_read_stream VALUES(?,?,?,?)',(self.failed,self.request,'read','[]'))
        with self.assertRaises(ValueError):self.register()

    def test_new_attempt_has_a_separate_observation_clock_and_preserves_old_window(self):
        with self.b.db() as con:old=tuple(con.execute('SELECT * FROM quality_review_observation_windows').fetchone())
        _,grant,_=self.resumed()
        context,state=review.load(self.b,self.source)
        identity=dict(namespace=self.b.PREFIX,source_task=self.source,request_id=grant['request_id'],
            assignment_sha256=review.quality.digest(context),assignment_state_sha256=review.quality.digest(state),packet_sha256=context['packet_sha256'])
        with patch.object(attestation.time,'time',return_value=100):
            window,expired=attestation.observation_window(self.b,self.source,identity,context)
        self.assertFalse(expired);self.assertEqual(window['deadline'],1900)
        with self.b.db() as con:
            self.assertEqual(tuple(con.execute('SELECT * FROM quality_review_observation_windows').fetchone()),old)
            self.assertEqual(con.execute('SELECT request_id FROM quality_review_attempt_windows').fetchone()[0],grant['request_id'])

    def test_inactive_attestation_corruption_is_still_rejected(self):
        self.resumed()
        with self.b.db() as con:con.execute("UPDATE quality_review_attestations SET receipt='{}'")
        with self.assertRaises(ValueError):attestation.load(self.b,self.source)

    def test_historical_receipt_can_be_read_without_migrating_a_readonly_archive(self):
        with self.b.db() as con:
            con.execute('DROP TABLE quality_review_attempt_attestations')
            con.execute('DROP TABLE quality_review_attempt_windows')
        original=self.b.db
        @contextmanager
        def readonly():
            with original() as con:
                con.execute('PRAGMA query_only=ON');yield con
        with patch.object(self.b,'db',readonly):
            self.assertEqual(attestation.load(self.b,self.source),self.old_attestation)

    def test_valid_new_attestation_does_not_overwrite_the_failed_old_review(self):
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
            con.execute('INSERT INTO acp_sessions VALUES(?,?)',(binding['scope'],'new-session'))
            for method in ('initialize','session/new','session/prompt'):
                con.execute('INSERT INTO acp_events VALUES(?,?,?,?)',(request,method,'new-session',1))
            con.execute("UPDATE leases SET status='closed' WHERE request_id=?",(request,))
            read_stream_receipts.store(con,binding,self.f.pages,'review')
        record.update(status='completed',result=dict(output=json.dumps(self.f.verdict)))
        receipt=attestation.observe(self.b,self.source)
        self.assertEqual(receipt['stage'],'tests_frozen')
        self.assertEqual(receipt['review_task'],self.next_task)
        self.assertEqual(receipt['request_id'],request)
        self.assertEqual(attestation.load(self.b,self.source,request_id=self.request),self.old_attestation)
        with self.b.db() as con:
            self.assertEqual(con.execute('SELECT request_id FROM quality_review_attempt_attestations').fetchone()[0],request)
            self.assertEqual(json.loads(con.execute('SELECT receipt FROM quality_review_attestations').fetchone()[0]),self.old_attestation)
        # Green must select the new freeze, not the old failed canonical row.
        from broker import quality_implementation_admission as implementation
        context,_=implementation.register(self.b,self.source)
        task='a0000000-0000-4000-8000-000000000005'
        wake=dict(id='a0000000-0000-4000-8000-000000000006',agent_id=context['author'],issue_id=context['issue_id'])
        with patch.object(recovery.native,'ensure_scope_author_start',return_value=wake):implementation.dispatch(self.b,self.source)
        self.native_records[task]=dict(id=task,agent_id=context['author'],issue_id=context['issue_id'],status='running',
            created_at='2026-10-23T20:00:00Z',
            workspace_id=self.old_task['workspace_id'],runtime_id=self.old_task['runtime_id'],wakeup_id=wake['id'],
            handoff_note='DELIVERY_SCOPE_AUTHOR_START '+context['marker']+'\nSource: '+context['origin']+'\n'+context['instruction'])
        product=implementation.admit(self.b,self.source,task,context['author'])
        with self.b.db() as con:bound=implementation.load(con,product['request_id'])
        self.assertEqual(bound['frozen_sha256'],review.quality.digest(receipt))
        self.assertNotEqual(bound['frozen_sha256'],review.quality.digest(self.old_attestation))
