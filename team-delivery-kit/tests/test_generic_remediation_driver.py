import json
import sqlite3
import threading
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from broker import generic_remediation_driver as driver


class GenericRemediationDriverTests(unittest.TestCase):
    def setUp(self):
        self.con=sqlite3.connect(':memory:');self.con.row_factory=sqlite3.Row
        self.addCleanup(self.con.close)
        @contextmanager
        def db():
            try:yield self.con;self.con.commit()
            except Exception:self.con.rollback();raise
        self.b=SimpleNamespace(db=db,LOCK=threading.RLock())
        self.config=dict(intake_kind='exhausted_frozen_suite_v1',source_task='source',root_issue='root',
            original_depth=2,revision_lineage=['second','first'],cto='cto',reviewer='lead')
        self.plan=dict(action='propose_remediation_plan',steps=['exact scoped plan'])
        sha=driver.plans.digest(self.plan)
        self.approved=dict(stage='plan_approved',plan=self.plan,plan_sha256=sha,plan_task='cto-task',
            review_task='lead-task',review=dict(decision='approve_plan',plan_sha256=sha),
            execution_authorized=False,release_homologated=False)
        self.fx=SimpleNamespace(idle=lambda:True,approved=lambda _: (self.config,self.approved),
            state=lambda _: (None,None,None))
        self.calls=[];self.fx.perform=lambda source,action:self.calls.append((source,action))

    def test_each_existing_adapter_stage_has_one_narrow_action(self):
        self.assertEqual(driver.next_action(None,None,None),'register_execution')
        for stage in ('r1_issue_intent','r1_issue_post_pending','r1_issue_observe'):
            self.assertEqual(driver.next_action(dict(stage=stage),None,None),'provision_issue')
        for stage in ('r1_provision_pending','r1_base_job_running','r1_seed_provision_pending'):
            self.assertEqual(driver.next_action(dict(stage=stage),None,None),'prepare_base')
        ready=dict(stage='r1_base_qualified')
        self.assertEqual(driver.next_action(ready,None,None),'prepare_context')
        ready['r1_runtime']={'qualified':True}
        self.assertEqual(driver.next_action(ready,None,None),'publish_context')
        self.assertEqual(driver.next_action(ready,dict(stage='published'),None),'request_full_chain')
        self.assertEqual(driver.next_action(ready,dict(stage='published'),dict(stage='awaiting_budget')),'await_delivery_gates')
        self.assertEqual(driver.next_action(dict(stage='r1_preparation_blocked'),None,None),'technical_hold')

    def test_changed_base_adapter_only_reopens_proven_pre_effect_hold(self):
        import copy
        self.config.update(amendment={'kind':'inherited_frozen_suite'},
            base=dict(issue_id='old',volume='old-volume',base_sha='a'*40,manifest_sha256='b'*64),
            source_issue='new',diagnostic_snapshot_kind='completed_frozen_validation')
        current={**self.config['base'],'issue_id':'new','volume':'new-volume'}
        prior=dict(stage='technical_hold',action='register_execution',category='ValueError')
        bound=driver.binding(self.config,self.approved)
        result=driver.changed_base_binding_state(self.config,self.approved,prior,bound,current,
            active=False,effects_present=False)
        self.assertEqual(result['stage'],'operation_pending');self.assertFalse(result['execution_authorized'])
        self.assertEqual(prior['stage'],'technical_hold')
        for change in ('active','effects','category','action','binding','base'):
            p,b,c=copy.deepcopy((prior,bound,current));flags=dict(active=False,effects_present=False)
            if change=='active':flags['active']=True
            if change=='effects':flags['effects_present']=True
            if change=='category':p['category']='TimeoutError'
            if change=='action':p['action']='provision_issue'
            if change=='binding':b['plan_sha256']='f'*64
            if change=='base':c['base_sha']='f'*40
            with self.subTest(change=change),self.assertRaises(ValueError):
                driver.changed_base_binding_state(self.config,self.approved,p,b,c,**flags)

    def test_restart_follows_adapter_ledger_not_previous_operation_text(self):
        first=driver.advance(self.b,'source',self.fx)
        self.assertEqual(first['action'],'register_execution')
        self.fx.state=lambda _: (dict(stage='r1_issue_post_pending'),None,None)
        driver.advance(self.b,'source',self.fx)
        self.assertEqual(self.calls,[('source','register_execution'),('source','provision_issue')])
        self.assertEqual(self.con.execute('SELECT count(*) FROM generic_remediation_drivers').fetchone()[0],1)
        bound=json.loads(self.con.execute('SELECT binding FROM generic_remediation_drivers').fetchone()[0])
        self.assertEqual(bound['original_depth'],2);self.assertFalse(bound['revision_depth_reset'])

    def test_live_approval_capacity_and_hash_binding_are_required(self):
        self.fx.idle=lambda:False
        self.assertEqual(driver.advance(self.b,'source',self.fx)['stage'],'awaiting_capacity')
        self.assertEqual(self.calls,[])
        self.fx.idle=lambda:True
        self.approved['review']['decision']='request_changes'
        with self.assertRaises(ValueError):driver.advance(self.b,'source',self.fx)
        self.assertEqual(self.calls,[])
        self.approved['review']['decision']='approve_plan'
        driver.advance(self.b,'source',self.fx)
        self.config['root_issue']='different-root'
        with self.assertRaises(ValueError):driver.advance(self.b,'source',self.fx)

    def test_approval_for_another_source_cannot_start_any_adapter(self):
        with self.assertRaises(ValueError):driver.advance(self.b,'other-source',self.fx)
        self.assertEqual(self.calls,[])

    def test_uncertain_operation_is_observed_from_existing_adapter_state(self):
        def timeout(*args):raise TimeoutError('uncertain remote effect')
        self.fx.perform=timeout
        state=driver.advance(self.b,'source',self.fx)
        self.assertEqual(state['stage'],'observe_existing_operation')
        self.fx.state=lambda _: (dict(stage='r1_base_job_running'),None,None)
        self.fx.perform=lambda source,action:self.calls.append((source,action))
        driver.advance(self.b,'source',self.fx)
        self.assertEqual(self.calls,[('source','prepare_base')])

    def test_semantic_rejection_is_visible_and_never_identically_retried(self):
        def reject(*args):raise ValueError('scope drift')
        self.fx.perform=reject
        state=driver.advance(self.b,'source',self.fx)
        self.assertEqual(state['stage'],'technical_hold')
        self.assertEqual(state['owner'],'cto')
        self.fx.approved=lambda _:self.fail('hold must not requalify and retry')
        self.assertEqual(driver.advance(self.b,'source',self.fx),state)
        self.assertFalse(state['release_homologated'])

    def test_full_chain_request_is_not_release_completion_or_repeat_request(self):
        self.fx.state=lambda _: (dict(stage='r1_base_qualified',r1_runtime={'qualified':True}),
            dict(stage='published'),dict(stage='phases_admitted'))
        state=driver.advance(self.b,'source',self.fx)
        self.assertEqual(state['stage'],'await_delivery_gates')
        self.assertFalse(state['release_homologated'])
        self.assertFalse(state['execution_authorized'])
        self.assertEqual(self.calls,[])
        self.fx.approved=lambda _:self.fail('admission supervisor owns next phases')
        self.assertEqual(driver.advance(self.b,'source',self.fx),state)

    def test_plan_review_requires_future_gates_not_impossible_preapproval_completion(self):
        from broker.technical_remediation_plan import instruction
        config=dict(self.config,required_paths=['/evidence/candidate/tests/test_new.py'])
        state=dict(stage='review_dispatch',plan=self.plan,plan_sha256=driver.plans.digest(self.plan))
        note=instruction(config,state)
        self.assertIn('plan review, not test or delivery review',note)
        self.assertIn('Current frozen tests are deliberately unchanged',note)
        self.assertIn('concrete missing or contradictory planned gate',note)
        self.assertIn('explicit experiment or evidence-producing R1 step',note)
        self.assertIn('later independent test review',note)
