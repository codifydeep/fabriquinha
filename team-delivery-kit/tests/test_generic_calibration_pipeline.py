import copy
import hashlib
import json
import sqlite3
import unittest

from broker import generic_calibration_pipeline as pipeline
from broker import generic_calibration_gate as gate
from generic_harness_calibration import digest,run
import test_generic_calibration_gate as samples


class PipelineTests(unittest.TestCase):
    def setUp(self):
        sample=samples.GenericCalibrationGateTests();sample.setUp();self.addCleanup(sample.doCleanups)
        self.record=gate.qualify(sample.policy,sample.context,sample.proposal,sample.review,sample.reads,sample.reads)
        self.receipt=run(sample.fixture.candidate,sample.fixture.controls,sample.policy,digest(sample.policy))
        self.c=dict(issue_id='issue',author_task='author-task',cto='cto',reviewer='lead')
        self.intake=dict(policy=sample.policy,context=sample.context,proposal_task='cto-task',review_task='lead-task')
        raw=json.dumps({'operation':'fixture-probe'})
        self.proof=dict(exit_code=0,approval=False,output=raw,output_sha256=hashlib.sha256(raw.encode()).hexdigest())
        self.con=sqlite3.connect(':memory:');self.addCleanup(self.con.close)
        self.con.execute('CREATE TABLE generic_calibration_workflows(issue_id TEXT,author_task TEXT,config TEXT,state TEXT)')
        self.initial=dict(stage='inputs_ready',policy_sha256=digest(sample.policy),intake_sha256=digest(self.intake),
            execution_authorized=False,delivery_approval=False)
        self.con.execute('INSERT INTO generic_calibration_workflows VALUES(?,?,?,?)',
            ('issue','author-task',json.dumps(self.c),json.dumps(self.initial)))
        self.events=[];parent=self
        class Effects:
            def verify(self,c):parent.assertEqual(c,parent.c)
            def pipeline_intake(self,c,s):return copy.deepcopy(parent.intake)
            def input_probe(self,c,s,intake):
                parent.assertEqual(parent.state()['stage'],'observe_inputs');parent.events.append('inputs')
                return copy.deepcopy(parent.proof)
            def register_policy(self,c,s,intake):
                parent.assertEqual(parent.state()['stage'],'register_policy');parent.events.append('register')
                return copy.deepcopy(parent.record)
            def calibrate(self,c,s,record):
                parent.assertEqual(parent.state()['stage'],'observe_calibration');parent.events.append('calibrate')
                return dict(receipt=copy.deepcopy(parent.receipt),delivery_approval=False)
            def registered_policy(self,c,s,intake):
                parent.assertEqual(parent.state()['stage'],'observe_calibration')
                return copy.deepcopy(parent.record)
        self.fx=Effects()

    def state(self):return json.loads(self.con.execute('SELECT state FROM generic_calibration_workflows').fetchone()[0])
    def advance(self,now=1):return pipeline.advance(self.con,self.c,self.fx,now=now)

    def test_fixed_pipeline_records_prerequisites_in_order_without_granting_red_or_delivery(self):
        self.advance();self.assertEqual(self.state()['stage'],'register_policy')
        self.advance(2);self.assertEqual(self.state()['stage'],'observe_calibration')
        self.advance(3);self.assertEqual(self.state()['stage'],'calibration_ready')
        self.assertEqual(self.events,['inputs','register','calibrate'])
        self.assertFalse(self.state()['execution_authorized']);self.assertFalse(self.state()['delivery_approval'])
        self.advance(4);self.assertEqual(len(self.events),3)

    def test_pending_job_observes_same_phase_never_registers_or_advances_early(self):
        original=self.fx.input_probe
        def pending(*a):original(*a);raise TimeoutError('same durable job')
        self.fx.input_probe=pending;self.advance()
        self.assertEqual(self.state()['stage'],'observe_inputs');self.assertNotIn('register',self.events)
        self.fx.input_probe=original;self.advance(2)
        self.assertEqual(self.state()['stage'],'register_policy')

    def test_changed_intake_is_owned_hold_before_docker_or_native_effects(self):
        self.intake['proposal_task']='stale'
        self.advance();self.assertEqual(self.state()['stage'],'blocked')
        self.assertEqual(self.state()['owner'],'cto');self.assertFalse(self.events)

    def test_failed_or_forged_probe_is_not_accepted_and_does_not_repeat(self):
        for change in ({'exit_code':1},{'approval':True},{'output_sha256':'stale'}):
            with self.subTest(change=change):
                self.con.execute('UPDATE generic_calibration_workflows SET state=?',(json.dumps(self.initial),))
                original=self.proof;self.proof={**original,**change};self.events=[]
                self.advance();self.assertEqual(self.state()['stage'],'blocked')
                self.advance(2);self.assertEqual(self.events,['inputs']);self.proof=original

    def test_registration_cannot_change_native_approval_identity(self):
        self.advance();self.record['context']['proposal_wakeup']='stale'
        self.advance(2);self.assertEqual(self.state()['stage'],'blocked')
        self.assertNotIn('calibrate',self.events)

    def test_actual_calibration_failure_or_fake_authority_is_preserved(self):
        self.advance();self.advance(2)
        self.receipt['red_approved']=True;self.advance(3)
        self.assertEqual(self.state()['stage'],'blocked');self.assertEqual(self.state()['owner'],'cto')
        self.advance(4);self.assertEqual(self.events.count('calibrate'),1)

    def test_restart_before_registration_ack_uses_same_immutable_native_record(self):
        self.advance();original=self.fx.register_policy
        def uncertain(*a):original(*a);raise TimeoutError('registration ack missing')
        self.fx.register_policy=uncertain;self.advance(2)
        self.assertEqual(self.state()['stage'],'register_policy')
        self.fx.register_policy=original;self.advance(3);self.advance(4)
        self.assertEqual(self.state()['stage'],'calibration_ready')
        self.assertEqual(self.events.count('inputs'),1)

    def test_repeated_observation_timeout_has_bounded_owned_hold_not_infinite_wait(self):
        def unavailable(c,s):raise TimeoutError('source observation unavailable')
        self.fx.pipeline_intake=unavailable;self.advance(1)
        self.assertEqual(self.state()['stage'],'inputs_ready');self.assertFalse(self.events)
        self.advance(1801);self.assertEqual(self.state()['stage'],'blocked')
        self.assertEqual(self.state()['category'],'calibration_prerequisite_deadline')
        self.assertEqual(self.state()['owner'],'cto');self.assertFalse(self.events)
