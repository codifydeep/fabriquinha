import copy
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from broker import diagnostic_maintenance_recovery as recovery, handoffs
from broker.diagnostic_maintenance_recovery import qualify, SERVER_SHA
from test_test_first_handoffs import Broker


class ObservationTests(unittest.TestCase):
    def evidence(self):
        return dict(maintenance=dict(stage='sealed',drained=True,namespace='delivery-kit-test',operation_id='operation'),
            namespace='delivery-kit-test',server_sha256=SERVER_SHA,stage='technical_decision_required',
            owner='cto',cto='cto',actor='cto',author='author',mode='planning',enabled=True,
            status='failed',wakeup='old-wake',expected_wakeup='old-wake',lease='interrupted',
            startup=dict(stage='failed',category='startup_transport_outcome_unknown'),
            data=dict(error='recipient_execution_failed',failed_dispatch_stage='diagnose_cto',
                recipient_task='failed',target='cto',artifact_diagnosis=True,
                validation_failure=dict(source_task='source'),
                unsupported_experiment_recovery=dict(attempt_limit=1,test_edits_authorized=False)),
            failed_task='failed',source_task='source',request_id='old-request',native_active=0,
            active_leases=0,old_container_exists=False,prior_recovery=None,
            mounts=[dict(Target='/evidence/candidate',Source='frozen',ReadOnly=True),
                    dict(Target='/evidence/previous',Source='red',ReadOnly=True)])

    def test_unknown_outcome_never_becomes_zero_calls_or_delivery(self):
        e=self.evidence(); before=copy.deepcopy(e); r=qualify(e)
        self.assertEqual(e,before); self.assertEqual(r['old_outcome'],'unknown')
        self.assertNotIn('model_calls',r); self.assertEqual(r['extra_observation_limit'],1)
        for key in ('old_capability_reused','author_retry_authorized','test_edits_authorized',
                    'experiment_retry_authorized','delivery_approval'):
            self.assertIs(r[key],False)

    def test_reject_authority_and_runtime_drift(self):
        for key,value in dict(mode='implementation',actor='author',enabled=False,status='running',
            wakeup='other',lease='running',native_active=1,active_leases=1,
            old_container_exists=True,prior_recovery={'used':True},server_sha256='a'*64).items():
            e=self.evidence();e[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):qualify(e)

    def test_sealed_and_both_readonly_frozen_artifacts_required(self):
        for change in ('released','wrong_namespace','writable','missing'):
            e=self.evidence()
            if change=='released':e['maintenance']['stage']='released'
            elif change=='wrong_namespace':e['maintenance']['namespace']='other'
            elif change=='writable':e['mounts'][0]['ReadOnly']=False
            else:e['mounts'].pop()
            with self.subTest(change=change),self.assertRaises(ValueError):qualify(e)

    def test_old_experiment_budget_and_failed_binding_cannot_change(self):
        for key,value in [('recipient_task','other'),('target','author'),('artifact_diagnosis',False)]:
            e=self.evidence();e['data'][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):qualify(e)
        e=self.evidence();e['data']['unsupported_experiment_recovery']['test_edits_authorized']=True
        with self.assertRaises(ValueError):qualify(e)


class DurableRecoveryTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.b=Broker(Path(tmp.name)/'state.sqlite');self.b.STATE=Path(tmp.name)
        self.b.LOCK=threading.RLock();self.b.PREFIX='delivery-kit-test'
        self.b.__file__=str(self.b.STATE/'controller.py');Path(self.b.__file__).write_bytes(b'qualified')
        self.b.docker=lambda *args:None
        (self.b.STATE/'native.json').write_text(json.dumps({'agents':{'cto':'planning'}}))
        self.source='11111111-1111-4111-8111-111111111111'
        self.failed='22222222-2222-4222-8222-222222222222'
        self.issue='33333333-3333-4333-8333-333333333333'
        self.operation='44444444-4444-4444-8444-444444444444'
        self.payload=dict(source_task=self.source,failed_task=self.failed,maintenance_operation=self.operation)
        self.e=ObservationTests().evidence();self.data=self.e['data']
        self.data.update(recipient_task=self.failed,wakeup_id='old-wake',instruction='old instruction',
                         diagnostic_revision='original',phase_evidence={'red':'unchanged'})
        self.data['validation_failure']['source_task']=self.source
        self.task=dict(id=self.failed,issue_id=self.issue,agent_id='cto',status='failed',wakeup_id='old-wake')
        with self.b.db() as c:
            handoffs.initialize(c);recovery.maintenance.initialize(c)
            c.execute('CREATE TABLE leases(request_id TEXT,status TEXT,name TEXT)')
            c.execute('CREATE TABLE native_bindings(request_id TEXT,task_id TEXT,agent_id TEXT,issue_id TEXT)')
            c.execute('CREATE TABLE acp_startups(request_id TEXT,state TEXT)')
            c.execute('INSERT INTO leases VALUES (?,?,?)',('request','interrupted','old-container'))
            c.execute('INSERT INTO native_bindings VALUES (?,?,?,?)',('request',self.failed,'cto',self.issue))
            c.execute('INSERT INTO acp_startups VALUES (?,?)',('request',json.dumps(self.e['startup'])))
            c.execute('INSERT INTO delivery_routes VALUES (?,?)',
                      (self.issue,json.dumps(dict(enabled=True,author='author',cto='cto'))))
            c.execute('INSERT INTO controller_maintenance VALUES (?,?,?)',
                (self.operation,'sealed',json.dumps(dict(stage='sealed',drained=True,
                    namespace=self.b.PREFIX,operation_id=self.operation))))
            handoffs.save(c,self.source,self.issue,'technical_decision_required','cto',self.data,1)
    def register(self):
        with patch.object(recovery,'SERVER_SHA',hashlib.sha256(b'qualified').hexdigest()),\
             patch.object(recovery.native,'task_record',return_value=self.task),\
             patch.object(recovery.maintenance,'native_active',return_value=[]),\
             patch.object(recovery.test_revision_review,'diagnostic_mounts',return_value=self.e['mounts']):
            return recovery.register(self.b,self.payload)

    def test_atomic_intent_preserves_incident_and_cannot_schedule_twice(self):
        receipt=self.register();self.assertEqual(self.register(),receipt)
        with self.b.db() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM diagnostic_maintenance_recoveries').fetchone()[0],1)
            row=handoffs.load(c,self.source);data=json.loads(row['data'])
            self.assertEqual(row['stage'],'diagnose_cto')
            self.assertEqual(data['validation_failure'],self.data['validation_failure'])
            self.assertEqual(data['phase_evidence'],self.data['phase_evidence'])
            self.assertNotIn('recipient_task',data);self.assertNotIn('wakeup_id',data)
            self.assertEqual(c.execute('SELECT status FROM leases').fetchone()[0],'interrupted')
        self.assertEqual(json.loads(receipt['previous_handoff']['data']),self.data)
        self.payload['failed_task']='55555555-5555-4555-8555-555555555555'
        with self.assertRaises(ValueError):self.register()

    def test_wrong_native_issue_or_nonsealed_state_never_changes_handoff(self):
        self.task['issue_id']='other'
        with self.assertRaises(ValueError):self.register()
        with self.b.db() as c:
            self.assertEqual(handoffs.load(c,self.source)['stage'],'technical_decision_required')
            self.assertEqual(c.execute('SELECT count(*) FROM diagnostic_maintenance_recoveries').fetchone()[0],0)
