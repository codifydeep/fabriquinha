import copy
import json
import sqlite3
import unittest
from types import SimpleNamespace

from broker import generic_calibration_gate as gate
from generic_harness_calibration import digest
import test_generic_harness_calibration as samples


class GenericCalibrationGateTests(unittest.TestCase):
    def setUp(self):
        fixture=samples.GenericCalibrationTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        self.fixture=fixture
        self.policy=fixture.policy
        self.context=dict(issue_id='issue',author_task='author-task',author='author',cto='cto',reviewer='lead',
            proposal_wakeup='proposal-wake',review_wakeup='review-wake',
            previous_methods=self.policy['previous_methods'],
            execution_sha256=self.policy['execution_sha256'],plan_sha256=self.policy['plan_sha256'],
            source_task=self.policy['source_task'],criteria=self.policy['criteria'],
            control_files=['positive.txt','negative.txt'],candidate_volume='delivery-kit-port2-candidate',
            controls_volume='delivery-kit-port2-controls',policy_volume='delivery-kit-port2-policy')
        def task(actor,wakeup,action):
            return dict(id=actor+'-task',agent_id=actor,issue_id='issue',status='completed',wakeup_id=wakeup,
                result=dict(output=json.dumps(dict(action=action,policy_sha256=digest(self.policy),
                    controls_manifest_sha256=self.policy['controls_manifest_sha256'],
                    execution_authorized=False,delivery_approval=False))))
        self.proposal=task('cto','proposal-wake','propose_calibration')
        self.review=task('lead','review-wake','approve_calibration')
        self.reads={path:dict(lines=4,total_lines=4) for path in gate.required_paths(self.policy,self.context)}

    def test_registration_requires_exact_independent_native_artifacts_and_full_reads(self):
        record=gate.qualify(self.policy,self.context,self.proposal,self.review,self.reads,self.reads)
        self.assertFalse(record['execution_authorized'])
        for mutate in (lambda t:t.update(agent_id='author'),lambda t:t.update(wakeup_id='stale'),
                       lambda t:t.update(status='running'),lambda t:t.update(id=self.proposal['id']),
                       lambda t:t['result'].update(output='{"action":"approve_calibration"}'),
                       lambda t:t['result'].update(output=json.dumps({
                           **json.loads(t['result']['output']),'execution_authorized':0}))):
            bad=copy.deepcopy(self.review);mutate(bad)
            with self.assertRaises(ValueError):gate.qualify(self.policy,self.context,self.proposal,bad,self.reads,self.reads)
        incomplete=copy.deepcopy(self.reads);incomplete[next(iter(incomplete))]['lines']=1
        with self.assertRaises(ValueError):gate.qualify(self.policy,self.context,self.proposal,self.review,self.reads,incomplete)

    def test_previous_method_inventory_and_execution_cannot_be_self_replaced(self):
        for mutate in (lambda c:c.update(previous_methods={}),lambda c:c.update(plan_sha256='0'*64),
                       lambda c:c.update(criteria=['A02'])):
            bad=copy.deepcopy(self.context);mutate(bad)
            with self.assertRaises(ValueError):gate.qualify(self.policy,bad,self.proposal,self.review,self.reads,self.reads)

    def test_registration_is_idempotent_but_not_replaceable(self):
        con=sqlite3.connect(':memory:');self.addCleanup(con.close)
        record=gate.qualify(self.policy,self.context,self.proposal,self.review,self.reads,self.reads)
        gate.store(con,record);gate.store(con,record)
        self.assertEqual(con.execute('SELECT count(*) FROM generic_calibration_policies').fetchone()[0],1)
        bad=copy.deepcopy(record);bad['context']['controls_volume']='another-volume'
        with self.assertRaises(ValueError):gate.store(con,bad)

    def test_payload_has_fixed_command_readonly_mounts_and_no_credentials_or_socket(self):
        record=gate.qualify(self.policy,self.context,self.proposal,self.review,self.reads,self.reads)
        b=SimpleNamespace(PREFIX='delivery-kit-port2',OWNER='owned',GENERIC_CALIBRATION_IMAGE='sha256:'+'c'*64)
        payload=gate.payload(b,record)
        self.assertEqual(payload['HostConfig']['NetworkMode'],'none')
        self.assertTrue(payload['HostConfig']['ReadonlyRootfs'])
        self.assertTrue(all(m['ReadOnly'] for m in payload['HostConfig']['Mounts']))
        self.assertEqual(payload['Env'],['PYTHONDONTWRITEBYTECODE=1'])
        self.assertEqual(payload['Cmd'][0],'/generic_harness_calibration.py')
        self.assertEqual(payload['Labels']['com.docker.compose.project'],'delivery-kit-port2-tests')
        for field in ('Image','Cmd','Env'):
            bad=copy.deepcopy(payload);bad[field]=[]
            with self.assertRaises(ValueError):gate.verify_payload(b,record,bad)

    def job(self,uncertain=None):
        from generic_harness_calibration import run
        record=gate.qualify(self.policy,self.context,self.proposal,self.review,self.reads,self.reads)
        con=sqlite3.connect(':memory:');self.addCleanup(con.close);gate.store(con,record);con.commit()
        b=SimpleNamespace(PREFIX='delivery-kit-port2',OWNER='owned',GENERIC_CALIBRATION_IMAGE='sha256:'+'c'*64)
        calls=[];container={}
        receipt=run(self.fixture.candidate,self.fixture.controls,self.policy,digest(self.policy))
        def docker(method,path,body=None):
            if path.startswith('/images/'):
                return dict(Id=b.GENERIC_CALIBRATION_IMAGE,Config=dict(Env=['PATH=/usr/bin']))
            if path.startswith('/volumes/'):
                role=path.rsplit('-',1)[-1]
                return dict(Labels={'delivery-kit.owner':'owned','delivery-kit.test-first-task':'author-task',
                    'delivery-kit.calibration-policy':digest(self.policy),'delivery-kit.calibration-role':role})
            calls.append((method,path))
            if method=='GET':return copy.deepcopy(container) if container else None
            if path.startswith('/containers/create'):
                container.update(Id='exact-container',Image=b.GENERIC_CALIBRATION_IMAGE,
                    Config={k:copy.deepcopy(v) for k,v in body.items() if k!='HostConfig'},
                    HostConfig=copy.deepcopy(body['HostConfig']),State=dict(Status='created',Running=False,ExitCode=0))
                if uncertain=='create':raise TimeoutError('acknowledgment lost')
                return {'Id':'exact-container'}
            container['State']=dict(Status='exited',Running=False,ExitCode=0)
            if uncertain=='start':raise TimeoutError('acknowledgment lost')
        b.docker=docker;b.docker_stdout=lambda *a,**k:json.dumps(receipt)
        return b,con,record,calls,container

    def test_uncertain_create_or_start_observes_existing_job_without_replay(self):
        for phase in ('create','start'):
            with self.subTest(phase=phase):
                b,con,record,calls,container=self.job(phase)
                with self.assertRaises(TimeoutError):gate.run(b,con,record,now=1)
                result=gate.run(b,con,record,now=2)
                self.assertFalse(result['delivery_approval'])
                self.assertEqual(sum(method=='POST' and '/create' in path for method,path in calls),1)
                self.assertEqual(sum(method=='POST' and '/start' in path for method,path in calls),1)
                count=len(calls);self.assertEqual(gate.run(b,con,record,now=4),result)
                self.assertEqual(len(calls),count)

    def test_missing_recorded_handle_is_never_recreated(self):
        b,con,record,calls,container=self.job('create')
        with self.assertRaises(TimeoutError):gate.run(b,con,record,now=1)
        container.clear()
        for now in (2,3):
            with self.assertRaises(TimeoutError):gate.run(b,con,record,now=now)
        self.assertEqual(sum(method=='POST' for method,path in calls),1)

    def test_failed_calibration_never_becomes_success_on_retry(self):
        b,con,record,calls,container=self.job()
        b.docker_stdout=lambda *a,**k:'{"status":"rejected"}'
        with self.assertRaises(ValueError):gate.run(b,con,record,now=1)
        count=len(calls)
        with self.assertRaises(ValueError):gate.run(b,con,record,now=2)
        self.assertEqual(len(calls),count)

