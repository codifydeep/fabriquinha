import copy
import hashlib
import json
import sqlite3
import unittest
import contextlib
from types import SimpleNamespace
from broker import maintained_test_calibration as lane
from unittest.mock import patch


class MaintainedCalibrationTests(unittest.TestCase):
    def test_ordinary_prerequisite_projection_is_persisted_without_enabling_product_route(self):
        from broker import generic_calibration_workflow as flow,handoffs
        handoffs.initialize(self.con)
        route=dict(issue_id='issue',enabled=False,cto='cto',author='author')
        self.con.execute('INSERT INTO delivery_routes VALUES(?,?)',('issue',json.dumps(route)))
        state=dict(stage='blocked',category='bundle_task_failed',owner='cto',execution_authorized=False,delivery_approval=False)
        @contextlib.contextmanager
        def db():
            yield self.con
            self.con.commit()
        task=dict(id='author',status='completed',issue_id='issue',agent_id='author')
        fx=lane.Effects(SimpleNamespace(db=db))
        cfg=dict(self.cfg,author='author',engine='unittest_path_fixtures_v2')
        with patch.object(flow,'request',return_value=state),patch.object(flow,'Effects',return_value=SimpleNamespace(
                plans=SimpleNamespace(task=lambda *args:task))):
            self.assertEqual(fx.calibration(cfg),state)
        parent=handoffs.load(self.con,'author')
        self.assertEqual(parent['stage'],'test_first_blocked')
        self.assertEqual(json.loads(parent['data'])['calibration_prerequisite'],state)
        self.assertFalse(json.loads(self.con.execute('SELECT config FROM delivery_routes').fetchone()[0])['enabled'])

    def setUp(self):
        self.con=sqlite3.connect(':memory:');self.con.row_factory=sqlite3.Row;self.addCleanup(self.con.close)
        self.cfg=dict(cto='cto',issue_id='issue',author_task='author',volume='owned-tests',
            prepared=dict(manifest_sha256='a'*64,test_sha256={'tests/test_one.py':'b'*64}))
        self.calls=[];self.pending=False;self.blocked=False
        raw=json.dumps(self.cfg['prepared'])
        result=dict(exit_code=0,approval=False,output=raw,output_sha256=hashlib.sha256(raw.encode()).hexdigest())
        def volume(c):
            self.calls.append('volume')
            if self.pending:raise TimeoutError('observe same intent')
        self.fx=SimpleNamespace(verify=lambda c:self.calls.append('verify'),volume=volume,
            copy=lambda c:copy.deepcopy(result),calibration=lambda c:dict(stage='blocked' if self.blocked else 'calibration_ready',
                category='native_hold',calibration_receipt={'exact':'proof'},execution_authorized=False,delivery_approval=False),
            red=lambda c,s:dict(issue_id='issue',task_id='author',volume='owned-tests',red=copy.deepcopy(c['prepared'])))
    def step(self):return lane.advance(self.con,'source',self.cfg,self.fx,now=100)
    def test_projection_then_independent_calibration_then_red_without_author_retry(self):
        self.assertEqual([self.step()['stage'] for _ in range(5)],
            ['volume_create_intent','copy','calibration','red','red_captured'])
        state=self.step();calls=list(self.calls);self.assertEqual(self.step(),state);self.assertEqual(calls,self.calls)
        for key in ('source_reset','author_retry_authorized','execution_authorized','delivery_approval'):self.assertFalse(state[key])
        self.assertEqual(state['red_receipt']['red'],self.cfg['prepared'])
    def test_pending_copy_observes_existing_phase_without_skipping_calibration(self):
        self.step();self.pending=True;self.assertEqual(self.step()['stage'],'volume_create_intent')
        self.pending=False;self.assertEqual(self.step()['stage'],'copy')
    def test_native_calibration_hold_stays_owned_and_can_resume_same_prerequisite(self):
        for _ in range(3):self.step()
        self.blocked=True;self.fx.red=lambda *args:self.fail('Red before calibration')
        s=self.step();self.assertEqual(s['stage'],'calibration');self.assertEqual(s['calibration_stage'],'blocked')
        self.assertEqual(s['owner'],'cto')
        self.assertEqual(self.step(),s)
        self.blocked=False;resumed=self.step();self.assertEqual(resumed['stage'],'red')
        self.assertIsNone(resumed['category'])
    def test_changed_copy_receipt_never_admits_calibration(self):
        self.step();self.step();self.fx.copy=lambda c:dict(exit_code=0,approval=False,output='{}',output_sha256='a'*64)
        self.fx.calibration=lambda *args:self.fail('invalid copy admitted')
        self.assertEqual(self.step()['stage'],'blocked')
    def test_red_from_another_snapshot_is_not_accepted(self):
        for _ in range(4):self.step()
        self.fx.red=lambda c,s:dict(issue_id='issue',task_id='author',volume='wrong',red=c['prepared'])
        self.assertEqual(self.step()['stage'],'blocked')
    def test_persisted_identity_cannot_be_replaced_on_restart(self):
        self.step();cfg=copy.deepcopy(self.cfg);cfg['volume']='replacement'
        with self.assertRaises(ValueError):lane.advance(self.con,'source',cfg,self.fx)
    def test_transient_prerequisite_observation_does_not_restart_projection(self):
        for _ in range(3):self.step()
        def pending(c):raise TimeoutError('exact existing calibration task')
        self.fx.calibration=pending
        for _ in range(2):self.assertEqual(self.step()['stage'],'calibration')
        self.assertEqual(self.calls.count('volume'),1)

    def test_policy_handoff_exposes_actual_native_owner_without_granting_authority(self):
        for _ in range(3):self.step()
        self.fx.calibration=lambda c:dict(stage='policy_review_wait',owner='lead',required_action='Review immutable policy',
            execution_authorized=False,delivery_approval=False)
        state=self.step();self.assertEqual(state['owner'],'lead')
        self.assertEqual(state['required_action'],'Review immutable policy');self.assertFalse(state['execution_authorized'])

    def test_volume_lost_ack_observes_same_effect_without_repeating_create(self):
        @contextlib.contextmanager
        def db():
            yield self.con
            self.con.commit()
        actual={};creates=[]
        c=dict(volume='owned-volume',labels={'delivery-kit.owner':'owner'})
        def docker(method,path,payload=None):
            if method=='GET':return actual.get(path)
            creates.append(payload);actual['/volumes/owned-volume']=copy.deepcopy(payload)
            raise TimeoutError('created, acknowledgment lost')
        fx=lane.Effects(SimpleNamespace(db=db,docker=docker))
        with self.assertRaises(TimeoutError):fx.volume(c)
        fx.volume(c);fx.volume(c);self.assertEqual(len(creates),1)
        actual['/volumes/owned-volume']['Labels']={}
        with self.assertRaises(ValueError):fx.volume(c)

    def test_functional_red_rejects_setup_error_baseline_failure_and_green(self):
        p=dict(manifest_sha256='a'*64,test_sha256={'tests/test_one.py':'b'*64},
            command=['python3','-m','unittest','discover','-s','.','-q'],test_count_pattern=r'Ran ([0-9]+) tests? in ',
            test_methods={'tests/test_one.py':['test_new']})
        def measured(output,exit_code=1):return dict(exit_code=exit_code,output=output,approval=False,
            output_sha256=hashlib.sha256(output.encode()).hexdigest())
        good='FAIL: test_new (tests.test_one.Tests.test_new)\nAssertionError: feature absent\nRan 2 tests in 0.1s\nFAILED (failures=1)\n'
        self.assertEqual(lane.assess_functional_red(measured(good),p)['exit_code'],1)
        for text,code in ((good.replace('FAIL:','ERROR:'),1),(good.replace('tests.test_one.','tests.test_old.'),1),
                ('Ran 2 tests in 0.1s\nOK\n',0),(good+'ERROR: test_old (tests.test_old.Tests.test_old)\n',1)):
            with self.subTest(text=text),self.assertRaises(ValueError):lane.assess_functional_red(measured(text,code),p)
