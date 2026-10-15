import copy
import json
import sqlite3
import types
import unittest
import test_calibration_objection_runtime as base
from broker import calibration_experiment_runtime as experiment,calibration_objection_runtime as runtime
from generic_harness_calibration import digest


class ExperimentRuntimeTests(base.ObjectionRuntimeTests):
    def setUp(self):
        super().setUp();self.c['criteria']={'A01':'Presence','A02':'Exact JSON','A03':'Polling','A04':'Stale responses'}
        self.c['prepared']['test_methods']={'tests/test.py':['test_ui']}
        # The fixture source is established before registration, never patched in a live workflow.
        self.con.execute('DELETE FROM calibration_objections');self.con.execute('UPDATE generic_calibration_workflows SET config=?',(json.dumps(self.c),))
        runtime.register(self.con,self.c,self.s)
        self.design_action='propose_fixture_experiment';self.review_action='permit_fixture_draft';self.wakes=[];self.uncertain_experiment=False
        parent=self
        def wake(cfg,s,actor,note,first):
            self.wakes.append((actor,first,s['experiment']['marker']))
            if self.uncertain_experiment:self.uncertain_experiment=False;raise TimeoutError()
            return dict(id=actor+'-experiment-wake')
        def decision(cfg,s,task,phase):
            v={**experiment.context(cfg,s,phase),'action':self.design_action if phase=='design' else self.review_action,
                'reason':'Full harness experiment, not measured results','author_retry_authorized':False,'execution_authorized':False,'delivery_approval':False}
            if phase=='design':v.update(hypothesis='Path controls can exercise frozen harness',method='Use positive references and criterion-specific negatives with full frozen tests',expected_evidence='All positives pass; negatives fail by their existing assertions')
            return dict(value=v,agent_id=self.c['cto' if phase=='design' else 'reviewer'],task_id=task['id'],wakeup_id=task['wakeup_id'],execution_id='experiment-'+phase)
        self.fx.experiment_wake=wake;self.fx.experiment_decision=decision
        self.fx.verify_experiment=lambda cfg,s:self.effects.append(('verify_experiment',))

    def held(self):
        self.action='retain_technical_hold';self.advance();self.advance();self.advance();self.completed();s=self.advance()
        self.assertEqual(s['category'],'objection_hold_retained');return s

    def finish_phase(self,actor):
        self.runs=[dict(id=actor+'-experiment-task',agent_id=actor,issue_id='spike',wakeup_id=actor+'-experiment-wake',status='completed')]

    def test_hold_dispatches_cto_then_independent_lead_without_repeating_old_spike(self):
        self.held();probes=sum(x[0]=='probe' for x in self.effects)
        self.advance();self.finish_phase('cto');s=self.advance();self.assertEqual(s['experiment']['stage'],'review_dispatch')
        self.advance();self.finish_phase('lead');s=self.advance();self.assertEqual(s['stage'],'resume_pending')
        s=self.advance();self.assertEqual(s['stage'],'referred');self.assertEqual(s['referral']['experiment']['stage'],'permitted')
        self.assertIn(('verify_experiment',),self.effects);self.assertEqual(sum(x[0]=='probe' for x in self.effects),probes)
        self.assertEqual([x[0] for x in self.wakes],['cto','lead'])
        self.assertFalse(s['referral']['execution_authorized']);self.assertFalse(s['referral']['tests_executed'])
        self.assertIn('not results/approval',runtime.addendum(s['referral']))
        before=copy.deepcopy(self.effects);self.advance();self.assertEqual(self.effects,before)

    def test_rejected_plan_is_visible_owned_and_cannot_rearm(self):
        self.held();self.advance();self.finish_phase('cto');self.advance();self.advance();self.finish_phase('lead');self.review_action='retain_technical_hold'
        s=self.advance();self.assertEqual(s['category'],'experiment_plan_rejected');self.assertEqual(s['owner'],'cto')
        before=list(self.wakes);self.advance();self.assertEqual(self.wakes,before)
        self.assertNotIn('referral',s)

    def test_unknown_wakeup_ack_observes_same_handle_and_never_creates_again(self):
        self.held();self.uncertain_experiment=True;self.advance();self.advance()
        self.assertEqual([x[1] for x in self.wakes],[True,False]);self.assertEqual(self.wakes[0][2],self.wakes[1][2])

    def test_cto_can_report_missing_capability_without_asking_ceo(self):
        self.held();self.advance();self.finish_phase('cto');self.design_action='needs_engineering_capability'
        s=self.advance();self.assertEqual(s['category'],'experiment_requires_engineering_capability');self.assertEqual(s['owner'],'cto')
        self.assertEqual(len(self.wakes),1)

    def test_wrong_actor_or_timed_out_evidence_cannot_be_permission(self):
        self.held();self.advance();self.finish_phase('cto');self.runs[0]['agent_id']='ceo'
        self.assertEqual(self.advance()['category'],'experiment_evidence_rejected')

    def test_evidence_observation_timeout_has_a_deadline(self):
        self.held();self.fx.verify_decision=lambda *_:(_ for _ in ()).throw(TimeoutError())
        self.assertEqual(self.advance(2)['experiment']['stage'],'design_dispatch')
        self.assertEqual(self.advance(1803)['category'],'experiment_evidence_observation_deadline')


class ExperimentNativeEvidenceTests(unittest.TestCase):
    def test_closed_native_identity_capsule_and_zero_tools_are_required(self):
        con=sqlite3.connect(':memory:');con.row_factory=sqlite3.Row;self.addCleanup(con.close)
        con.executescript('CREATE TABLE native_bindings(request_id,task_id,agent_id,issue_id,scope);'
            'CREATE TABLE leases(request_id,status);CREATE TABLE tool_events(request_id,tool_count);'
            "INSERT INTO native_bindings VALUES('exec','task','cto','spike','run:planning:task');"
            "INSERT INTO leases VALUES('exec','closed');")
        cfg=dict(source=dict(cto='cto',reviewer='lead'));s=dict(issue_id='spike',decision={'value':'original hold'},
            experiment=dict(wakeup_id='design-wake'))
        value={**experiment.context(cfg,s,'design'),'action':'propose_fixture_experiment',
            'reason':'Propose reference fixtures','hypothesis':'Frozen harness supports fixtures','method':'Run existing full harness',
            'expected_evidence':'Positive pass and criterion negative failure','author_retry_authorized':False,'execution_authorized':False,'delivery_approval':False}
        task=dict(id='task',agent_id='cto',issue_id='spike',wakeup_id='design-wake',status='completed',
            handoff_note=experiment.contract.capsule(experiment.context(cfg,s,'design')),result=dict(output=json.dumps(value)))
        fx=runtime.Effects.__new__(runtime.Effects);fx.b=types.SimpleNamespace(db=lambda:con)
        fx.plans=types.SimpleNamespace(task=lambda task_id,actor:task)
        receipt=fx.experiment_decision(cfg,s,task,'design');self.assertEqual(receipt['wakeup_id'],'design-wake')
        # A later review may replace the current handle, never the proposal's identity.
        s['experiment'].update(proposal=receipt,wakeup_id='review-wake')
        self.assertEqual(fx.experiment_decision(cfg,s,task,'design'),receipt)
        con.execute("INSERT INTO tool_events VALUES('exec',1)")
        with self.assertRaises(ValueError):fx.experiment_decision(cfg,s,task,'design')
        con.execute('DELETE FROM tool_events');task['wakeup_id']='foreign'
        with self.assertRaises(ValueError):fx.experiment_decision(cfg,s,task,'design')
        task['wakeup_id']='design-wake';con.execute("UPDATE leases SET status='running'")
        with self.assertRaises(TimeoutError):fx.experiment_decision(cfg,s,task,'design')
