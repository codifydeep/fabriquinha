import copy
import json
import unittest
from broker import literal_maintenance_workflow as flow
from broker import author_feedback_admission as admission
import test_literal_maintenance_workflow as fixture


class FeedbackWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.f=fixture.LiteralWorkflowTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.before=self.f.con.execute('SELECT config,state FROM literal_maintenance_workflows WHERE source_task=?',('source',)).fetchone()
        self.p=dict(source_task='rejected-author',issue_id='maintenance',author='author',cto='cto',reviewer='lead',
            test_path='tests/test.py',previous_manifest_sha256='a'*64,qualification_sha256='b'*64,
            expected=dict(initial_expected=1,poll_minimum=3,stale_expected='Newest matching: #11'))
        self.f.cfg=dict(self.f.cfg,workflow_key='rejected-author',feedback_strategy=dict(policy=self.p))
        flow.register(self.f.con,self.f.cfg)
        old=self.f.fx.decision
        def decision(cfg,s,phase,t):
            if phase not in ('plan','permit'):return old(cfg,s,phase,t)
            value=dict(admission.context(self.p),action='refer_to_cto',reason='New feedback contract, same immutable acceptance',
                author_retry_authorized=False,execution_authorized=False,delivery_approval=False)
            return dict(task_id=t['id'],agent_id=t['agent_id'],wakeup_id=t['wakeup_id'],value=value,output_sha256='d'*64)
        self.f.fx.decision=decision

    def advance(self):return flow.advance(self.f.con,'rejected-author',self.f.fx,now=1)

    def reach_author(self):
        self.assertEqual(self.advance()['stage'],'plan_wait')
        self.f.complete('plan');self.assertEqual(self.advance()['stage'],'permit_dispatch')
        self.assertEqual(self.advance()['stage'],'permit_wait')
        self.f.complete('permit');self.assertEqual(self.advance()['stage'],'prepare')
        self.assertEqual(self.advance()['stage'],'author_dispatch')

    def submit(self):
        self.reach_author();self.advance();self.f.complete('author');self.advance();self.advance();self.advance()
        self.advance();self.f.complete('review');return self.advance()

    def test_new_source_key_preserves_predecessor_and_delivers_only_after_independent_review(self):
        state=self.submit();self.assertEqual(state['stage'],'maintenance_approved')
        self.assertEqual(set(state['decisions']),{'plan','permit'})
        self.assertFalse(state['source_reset']);self.assertFalse(state['delivery_approval'])
        self.assertEqual(tuple(self.f.con.execute('SELECT config,state FROM literal_maintenance_workflows WHERE source_task=?',('source',)).fetchone()),tuple(self.before))
        phases=[c[1] for c in self.f.calls if c[0]=='wake'];self.assertEqual(phases,['plan','permit','author','review'])

    def test_new_key_cannot_reset_ordinary_workflow_or_alias_another_scope(self):
        original=json.loads(self.before[0])
        with self.assertRaises(ValueError):flow.register(self.f.con,dict(original,workflow_key='reset'))
        with self.assertRaises(ValueError):flow.register(self.f.con,dict(self.f.cfg,workflow_key='wrong-scope'))
        self.assertEqual(self.f.con.execute('SELECT count(*) FROM literal_maintenance_workflows').fetchone()[0],2)

    def test_rejection_preserves_artifact_and_blocks_without_identical_retry(self):
        self.f.review_choice='reject_test_revision';state=self.submit()
        self.assertEqual(state['stage'],'blocked');self.assertEqual(state['category'],'maintenance_feedback_strategy_rejected')
        self.assertEqual(len(state['history']),1);before=copy.deepcopy(self.f.calls)
        self.assertEqual(self.advance(),state);self.assertEqual(self.f.calls,before)

    def test_uncertain_wakeup_is_observed_never_recreated(self):
        self.f.timeout=True;self.assertEqual(self.advance()['stage'],'plan_observe')
        self.assertEqual(self.advance()['stage'],'plan_wait')
        calls=[c for c in self.f.calls if c[0]=='wake'];self.assertEqual([c[2] for c in calls],[True,False])
        self.assertEqual(calls[0][3],admission.marker(self.p,'cto'))

    def test_installed_proxy_contract_preflight_uses_bound_referral_not_old_technical_schema(self):
        self.assertEqual(len(flow.preflight_plan(self.f.cfg,{},'plan')),64)
        self.reach_author();state=json.loads(self.f.con.execute('SELECT state FROM literal_maintenance_workflows WHERE source_task=?',('rejected-author',)).fetchone()[0])
        note=flow.instruction(self.f.cfg,state,'permit')
        self.assertIn('CTO proposal evidence',note);self.assertIn('d'*64,note)
        self.assertEqual(len(flow.preflight_plan(self.f.cfg,state,'permit')),64)
