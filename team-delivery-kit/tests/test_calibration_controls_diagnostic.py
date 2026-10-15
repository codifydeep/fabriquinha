import copy
import json
import sqlite3
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from broker import calibration_controls_diagnostic as runtime
from generic_harness_calibration import digest


class ControlsDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.con=sqlite3.connect(':memory:');self.con.row_factory=sqlite3.Row;self.addCleanup(self.con.close);runtime.initialize(self.con)
        self.c=dict(issue_id='origin',author_task='author',cto='cto',reviewer='lead',test_files=['tests/test.py'],
            calibration_engine='unittest_path_fixtures_v2',criteria={'A01':'Behavior'},
            prepared=dict(manifest_sha256='a'*64,test_sha256={'tests/test.py':'b'*64}))
        self.cfg=dict(source=self.c,objection_config={'original':'config'},hold={'original':'hold'},
            plan_evidence={'proposal':{'task_id':'cto-plan'},'review':{'task_id':'lead-plan'}},parent_issue_id='parent')
        runtime.register(self.con,self.cfg);self.calls=[];self.runs=[];self.uncertain=False;self.pass_controls=True;self.review='refer_to_cto';parent=self
        class Effects:
            def verify(_,cfg):parent.assertEqual(cfg,parent.cfg)
            def reserve(_):return True
            def issue(_,cfg,first):parent.calls.append(('issue',first));return {'id':'spike','identifier':'EVAL-DIAGNOSTIC'}
            def wake(_,cfg,s,phase,first):
                parent.calls.append(('wake',phase,first,s['marker']))
                if parent.uncertain:parent.uncertain=False;raise TimeoutError()
                return {'id':phase+'-wake'}
            def runs(_,cfg,s):return parent.runs
            def collect(_,cfg,s,task):return {'operation':'generic_calibration_proposal_bundle_v1','producer':{'task_id':task['id']},'controls':{'reference.js':'untrusted'}}
            def measure(_,cfg,s):
                parent.calls.append(('measure',));return {'approval':False,'receipt':{'functional_controls_passed':parent.pass_controls}}
            def validate_measurement(_,cfg,s,result):parent.assertFalse(result['approval'])
            def decision(_,cfg,s,task):return {'task_id':task['id'],'agent_id':'lead','value':{
                **runtime.review_context(cfg,s),'action':parent.review,'reason':'Measured controls, not product approval',
                'author_retry_authorized':False,'execution_authorized':False,'delivery_approval':False}}
        self.fx=Effects()

    def advance(self,now=1):return runtime.advance(self.con,'origin','author',self.fx,now=now)
    def completed(self,phase):self.runs=[dict(id=phase+'-task',agent_id='cto' if phase=='producer' else 'lead',issue_id='spike',wakeup_id=phase+'-wake',status='completed')]

    def test_actual_measurements_precede_independent_referral_without_source_author_retry(self):
        self.advance();self.advance();self.completed('producer');self.advance();s=self.advance()
        self.assertEqual(s['stage'],'review_dispatch');self.assertIn(('measure',),self.calls)
        self.advance();self.completed('review');s=self.advance();self.assertEqual(s['stage'],'referred')
        self.assertFalse(s['delivery_approval']);self.assertFalse(s['execution_authorized'])
        before=copy.deepcopy(self.calls);self.advance();self.assertEqual(self.calls,before)

    def test_failed_controls_are_preserved_without_review_or_automatic_replay(self):
        self.advance();self.advance();self.completed('producer');self.advance();self.pass_controls=False
        s=self.advance();self.assertEqual(s['category'],'diagnostic_controls_failed');self.assertEqual(s['owner'],'cto')
        before=list(self.calls);self.advance();self.assertEqual(self.calls,before)
        self.assertNotIn(('wake','review',True),[x[:3] for x in self.calls])

    def test_lost_wakeup_ack_observes_same_marker_without_duplicate_creation(self):
        self.advance();self.uncertain=True;self.advance();self.advance()
        wakes=[x for x in self.calls if x[0]=='wake'];self.assertEqual([x[2] for x in wakes],[True,False]);self.assertEqual(wakes[0][3],wakes[1][3])

    def test_wrong_actor_or_expired_observation_cannot_sponsor_submission(self):
        self.advance();self.advance();self.completed('producer');self.runs[0]['agent_id']='ceo'
        self.assertEqual(self.advance()['category'],'diagnostic_evidence_rejected')

    def test_missing_native_run_has_a_deadline_and_keeps_original_handoff(self):
        self.advance();self.advance();self.assertEqual(self.advance(1802)['category'],'diagnostic_native_deadline')

    def test_changed_configuration_cannot_rearm_the_same_experiment(self):
        with self.assertRaises(ValueError):runtime.register(self.con,{**self.cfg,'hold':{'changed':'wording'}})

    def test_readonly_context_requires_registered_phase_actor_wakeup_and_source(self):
        self.advance();self.advance();task=dict(id='producer-task',agent_id='cto',issue_id='spike',wakeup_id='producer-wake')
        b=SimpleNamespace(db=lambda:self.con);note=runtime.wire.capsule(runtime.producer_context(self.cfg))
        with patch.object(runtime,'Effects',return_value=self.fx):
            self.assertEqual(runtime.prompt_contract(b,'spike',task,note),runtime.producer_context(self.cfg))
            for bad in ({**task,'agent_id':'author'},{**task,'wakeup_id':'foreign'}):
                with self.assertRaises(ValueError):runtime.prompt_contract(b,'spike',bad,note)
            with self.assertRaises(ValueError):runtime.prompt_contract(b,'spike',task,note.replace(digest(self.cfg),'f'*64))
        self.assertIsNone(runtime.lookup(b,None));self.assertIsNone(runtime.lookup(b,'unregistered'))

    def test_reference_mounts_are_readonly_and_bound_to_one_live_native_task(self):
        self.c.update(candidate_volume='delivery-kit-port2-candidate',previous_volume='delivery-kit-port2-previous')
        self.con.execute('DELETE FROM calibration_control_experiments');runtime.register(self.con,self.cfg)
        self.advance();self.advance()
        self.con.executescript("CREATE TABLE native_bindings(request_id,task_id,agent_id,issue_id,scope);CREATE TABLE leases(request_id,status);"
            "INSERT INTO native_bindings VALUES('exec','task','cto','spike','root:cto:planning:task');INSERT INTO leases VALUES('exec','running');")
        task=dict(id='task',agent_id='cto',issue_id='spike',wakeup_id='producer-wake')
        self.fx.plans=SimpleNamespace(task=lambda *_:task);b=SimpleNamespace(db=lambda:self.con)
        with patch.object(runtime,'Effects',return_value=self.fx):
            mounted=runtime.mounts(b,dict(issue_id='spike',agent_id='cto'))
            self.assertEqual({m['Target'] for m in mounted},{'/evidence/candidate','/evidence/previous'})
            self.assertTrue(all(m['ReadOnly'] is True for m in mounted))
            task['wakeup_id']='foreign'
            with self.assertRaises(ValueError):runtime.mounts(b,dict(issue_id='spike',agent_id='cto'))

    def test_measured_referral_cannot_be_reused_after_control_or_review_drift(self):
        self.advance();self.advance();self.completed('producer');self.advance();self.advance();self.advance();self.completed('review');s=self.advance()
        pointer=runtime.referral(self.cfg,s);runtime.cached_referral(self.con,self.c,pointer)
        s['result']['receipt']['functional_controls_passed']=False
        self.con.execute('UPDATE calibration_control_experiments SET state=?',(json.dumps(s),));self.con.commit()
        with self.assertRaises(ValueError):runtime.cached_referral(self.con,self.c,pointer)
