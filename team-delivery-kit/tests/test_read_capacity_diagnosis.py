import json
import sqlite3
import unittest
import hashlib
from pathlib import Path
import tempfile
import threading
from unittest.mock import patch
from broker.read_capacity_diagnosis import validate,qualified,register,PROXY_IMAGE
from broker import handoffs
from test_test_first_handoffs import Broker

TASK='01a112df-4a33-764e-9615-d277767c777c'
SESSION='7d184b26-cec9-4c8b-8bc4-fad5d2f001fd'


class ReadCapacityDiagnosisTests(unittest.TestCase):
    def proof(self):
        return dict(operation='frozen_native_read_page_probe_v2',source_task=TASK,session_id=SESSION,
            manifest_sha256='a'*64,policy_sha256='b'*64,baseline_unchanged=True,
            test_sha256={'tests/test_new.py':'c'*64},files=4,calls_50=28,calls_200=9,
            historical_tool_turns=40,all_lines_observed=True,snapshot_unchanged=True,
            model_calls=0,agent_inspection_verified=False,delivery_approval=False,full_rpc_qualified=False)

    def test_capacity_is_not_inspection_tdd_or_permission_to_retry(self):
        validate(self.proof())
        for key,value in [('delivery_approval',True),('agent_inspection_verified',True),
                ('model_calls',1),('baseline_unchanged',False),('all_lines_observed',False),
                ('calls_200',28),('historical_tool_turns',39),('policy_sha256','bad')]:
            with self.assertRaises(ValueError):validate({**self.proof(),key:value})

    def test_only_matching_durable_certificate_qualifies(self):
        c=sqlite3.connect(':memory:');self.addCleanup(c.close)
        self.assertFalse(qualified(c,'issue',TASK,{}))
        c.execute('CREATE TABLE read_capacity_diagnoses(issue_id TEXT PRIMARY KEY,receipt TEXT)')
        receipt=dict(operation='read_capacity_diagnosis_v1',issue_id='issue',source_task=TASK,
                     diagnostic={},probe=self.proof(),author_retry_authorized=False,delivery_approval=False)
        c.execute('INSERT INTO read_capacity_diagnoses VALUES (?,?)',('issue',json.dumps(receipt)))
        self.assertTrue(qualified(c,'issue',TASK,{'read_capacity_diagnosis':receipt,'diagnostic':{}}))
        self.assertFalse(qualified(c,'issue','other',{'read_capacity_diagnosis':receipt}))
        self.assertFalse(qualified(c,'issue',TASK,{'read_capacity_diagnosis':{
            **receipt,'author_retry_authorized':True}}))


class ReadCapacityRegistrationTests(ReadCapacityDiagnosisTests):
    def setUp(self):
        from author_read_policy import page_size
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name);self.b=Broker(root/'state.sqlite');self.b.STATE=root
        self.b.LOCK=threading.RLock();self.b.PREFIX='delivery-kit-eval'
        self.b.docker=lambda *args:dict(Image=PROXY_IMAGE,State=dict(Running=True))
        (root/'native.json').write_text('{}')
        self.issue='01a112a7-fe96-7ae9-b98f-e7e85bd5dacf'
        self.probe=self.proof();self.probe['policy_sha256']=hashlib.sha256(Path(page_size.__code__.co_filename).read_bytes()).hexdigest()
        self.route=dict(enabled=True,test_first=True,author='author',cto='cto',
                        issue_id=self.issue,test_first_files=['tests/test_new.py'])
        self.runs=[dict(id=TASK,status='failed',agent_id='author',created_at='2',wakeup_id='corrective'),
                   dict(id='cto-decision',status='completed',agent_id='cto',created_at='1')]
        with self.b.db() as c:
            handoffs.initialize(c)
            c.execute('CREATE TABLE leases(status TEXT)')
            c.execute('CREATE TABLE test_first_red(issue_id TEXT)')
            c.execute('CREATE TABLE failed_execution_snapshots(task_id TEXT,status TEXT,volume TEXT)')
            c.execute('CREATE TABLE native_bindings(task_id TEXT,request_id TEXT)')
            c.execute('CREATE TABLE acp_events(request_id TEXT,method TEXT,success INT,session_id TEXT)')
            c.execute('INSERT INTO delivery_routes VALUES (?,?)',(self.issue,json.dumps(self.route)))
            c.execute('INSERT INTO failed_execution_snapshots VALUES (?,?,?)',(TASK,'complete','frozen'))
            c.execute('INSERT INTO native_bindings VALUES (?,?)',(TASK,'execution'))
            c.execute('INSERT INTO acp_events VALUES (?,?,?,?)',('execution','session/new',1,SESSION))
            handoffs.save(c,'prior',self.issue,'test_first_cto_correction_wait','cto',dict(
                test_first_correction_wakeup='corrective',cto_task='cto-decision',
                decision=dict(action='request_correction')),1)
            handoffs.save(c,TASK,self.issue,'test_first_blocked','cto',dict(
                error='test_first_correction_failed_after_cto_diagnosis'),2)

    def call(self):
        with patch('broker.native.issue_task_runs',return_value=self.runs):
            return register(self.b,self.issue,TASK,self.probe)

    def test_once_diagnosis_preserves_failure_and_never_dispatches_author(self):
        receipt=self.call();self.assertEqual(self.call(),receipt)
        with self.b.db() as c:
            row=handoffs.load(c,TASK);data=json.loads(row['data'])
            self.assertEqual(row['stage'],'technical_decision_required');self.assertEqual(row['owner'],'cto')
            self.assertTrue(qualified(c,self.issue,TASK,data))
            self.assertEqual(c.execute('SELECT count(*) FROM test_first_red').fetchone()[0],0)
        self.assertFalse(receipt['author_retry_authorized'])
        self.assertEqual(json.loads(receipt['prior']['data'])['error'],
                         'test_first_correction_failed_after_cto_diagnosis')
        self.probe={**self.probe,'manifest_sha256':'d'*64}
        with self.assertRaisesRegex(ValueError,'already consumed'):self.call()

    def test_unrelated_session_red_or_active_worker_cannot_reopen(self):
        self.probe['session_id']='7d184b26-cec9-4c8b-8bc4-fad5d2f001fe'
        with self.assertRaisesRegex(ValueError,'exact native session'):self.call()
        self.probe['session_id']=SESSION
        with self.b.db() as c:c.execute('INSERT INTO leases VALUES (?)',('running',))
        with self.assertRaisesRegex(ValueError,'idle latest'):self.call()

    def test_no_cto_lineage_or_installed_policy_no_recovery(self):
        self.runs[1]['status']='failed'
        with self.assertRaisesRegex(ValueError,'independent CTO'):self.call()
        self.runs[1]['status']='completed';self.probe['policy_sha256']='d'*64
        with self.assertRaisesRegex(ValueError,'not installed'):self.call()
