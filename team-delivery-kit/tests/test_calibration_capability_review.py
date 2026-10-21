import copy
import hashlib
import json
import sqlite3
import unittest
import contextlib
from types import SimpleNamespace
from unittest.mock import Mock,patch

from broker import calibration_capability_review as review
from generic_harness_calibration import digest
import reference_fixture_capability_probe as probe


class CapabilityReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.measured=probe.run()

    def setUp(self):
        self.con=sqlite3.connect(':memory:');self.con.row_factory=sqlite3.Row;self.addCleanup(self.con.close)
        self.c=dict(issue_id='origin',author_task='author',cto='cto',reviewer='lead',
            calibration_engine='unittest_path_fixtures_v2',test_files=['tests/test.py'])
        paths=['/evidence/candidate/app/app.js','/evidence/candidate/app/index.html',
            '/evidence/candidate/tests/test.py','/evidence/previous/tests/test.py']
        self.original=dict(source=self.c,objection=dict(read_evidence={p:dict(lines=10,total_lines=10) for p in paths}))
        flags=dict(author_retry_authorized=False,execution_authorized=False,delivery_approval=False)
        self.parent=dict(stage='blocked',category='experiment_requires_engineering_capability',issue_id='parent',
            decision=dict(task_id='old-lead',agent_id='lead',value=dict(action='retain_technical_hold',**flags)),
            experiment=dict(stage='blocked',category='experiment_requires_engineering_capability',
                proposal=dict(task_id='request-task',agent_id='cto',value=dict(action='needs_engineering_capability',
                    reason='Feature is absent',hypothesis='Need product implementation',method='Ask engineering',expected_evidence='New snapshot',**flags))))
        self.cfg=review.configuration(self.original,self.parent,'sha256:'+'a'*64)
        review.register(self.con,self.cfg);self.runs=[];self.wakes=[];self.choice='refer_to_cto';self.uncertain=False
        raw=json.dumps(copy.deepcopy(self.measured));self.job=dict(output=raw,output_sha256=hashlib.sha256(raw.encode()).hexdigest(),
            exit_code=0,approval=False,validation_job_key='job',container_id='fixed-helper')
        def wake(cfg,s,first):
            self.wakes.append((first,s['marker']))
            if self.uncertain:self.uncertain=False;raise TimeoutError('unknown acknowledgement')
            return dict(id='capability-wake')
        self.fx=SimpleNamespace(verify=lambda cfg:None,measure=lambda cfg:copy.deepcopy(self.job),reserve=lambda:True,
            issue=lambda cfg,first:dict(id='capability-issue',identifier='EVAL-CAP'),wake=wake,runs=lambda cfg,s:self.runs,
            decision=lambda cfg,s,t:dict(task_id=t['id'],agent_id=t['agent_id'],execution_id='review-execution',
                value={**review.context(cfg,s),**flags,'action':self.choice,'reason':'Diagnostic only, not product approval'}))

    def step(self,now=100):return review.advance(self.con,self.cfg,self.fx,now=now)

    def waiting(self):
        self.step();self.step();return self.step()

    def complete(self):
        self.runs=[dict(id='capability-review',agent_id='lead',issue_id='capability-issue',
            wakeup_id='capability-wake',status='completed')]
        return self.step()

    def test_fixed_proof_and_independent_review_precede_diagnostic_only_permission(self):
        self.waiting();state=self.complete()
        self.assertEqual(state['stage'],'permitted')
        receipt=review.qualified(self.con,self.cfg,state)
        self.assertEqual(receipt['capability_request'],self.parent['experiment']['proposal'])
        self.assertEqual(receipt['diagnostic_attempt_limit'],1)
        for key in ('author_retry_authorized','execution_authorized','delivery_approval','source_reset','retry_budget_reset'):
            self.assertIs(receipt[key],False)
        diagnostic=review.diagnostic_configuration(self.cfg,state)
        self.assertEqual(diagnostic['capability_admission']['required_paths'],sorted(self.original['objection']['read_evidence']))
        self.assertNotIn('plan_evidence',diagnostic)
        self.assertEqual(self.parent['experiment']['proposal']['value']['action'],'needs_engineering_capability')
        before=list(self.wakes);self.step();self.assertEqual(before,self.wakes)

    def test_no_proof_or_review_can_be_replaced_by_a_model_claim(self):
        self.job['output_sha256']='0'*64
        self.assertEqual(self.step()['stage'],'blocked');self.assertEqual(self.wakes,[])
        self.assertEqual(self.step()['stage'],'blocked')

    def test_unknown_wakeup_only_observes_same_marker_and_never_reposts(self):
        self.step();self.step();self.uncertain=True
        self.assertEqual(self.step()['stage'],'review_observe')
        self.step();self.assertEqual([x[0] for x in self.wakes],[True,False])
        self.assertEqual(self.wakes[0][1],self.wakes[1][1])

    def test_hold_failed_native_or_foreign_actor_never_opens_diagnostic(self):
        self.waiting();self.choice='retain_technical_hold'
        self.assertEqual(self.complete()['category'],'capability_hold_retained')
        with self.assertRaises(ValueError):review.diagnostic_configuration(self.cfg,self.step())

    def test_foreign_actor_and_failed_task_have_no_automatic_retry(self):
        self.waiting();self.runs=[dict(id='foreign',agent_id='cto',issue_id='capability-issue',
            wakeup_id='capability-wake',status='completed')]
        self.assertEqual(self.step()['stage'],'blocked')
        before=list(self.wakes);self.step();self.assertEqual(self.wakes,before)

    def test_missing_native_acknowledgement_has_bounded_owned_hold(self):
        self.step();self.step();self.fx.wake=lambda *args:None
        self.assertEqual(self.step()['stage'],'review_observe')
        self.assertEqual(self.step(now=701)['category'],'capability_wakeup_unobserved')

    def test_changed_source_or_consumed_registration_cannot_reset_permission(self):
        with self.assertRaises(ValueError):review.register(self.con,{**self.cfg,'image':'sha256:'+'b'*64})
        self.assertEqual(self.con.execute('SELECT count(*) FROM calibration_capability_reviews').fetchone()[0],1)
        self.waiting();state=self.complete();state['measurement_job']['output_sha256']='0'*64
        with self.assertRaises(ValueError):review.qualified(self.con,self.cfg,state)

    def test_configuration_does_not_treat_any_technical_block_as_capability_request(self):
        for mutate in (lambda s:s.update(category='unrelated'),
                lambda s:s['experiment']['proposal']['value'].update(action='propose_fixture_experiment'),
                lambda s:s['decision'].update(agent_id='cto')):
            state=copy.deepcopy(self.parent);mutate(state)
            with self.subTest(mutate=mutate),self.assertRaises(ValueError):review.configuration(self.original,state,self.cfg['image'])

    def test_instruction_is_bounded_and_uses_existing_independent_review_contract(self):
        state=self.step()
        from calibration_objection_contract import request,apply
        note=review.instruction(self.cfg,state)
        self.assertLessEqual(len(note),3800)
        self.assertEqual(request(dict(messages=[dict(role='user',content=note)])),review.context(self.cfg,state))
        body=apply(dict(messages=[dict(role='user',content=note)],tools=[dict(name='terminal')]))
        self.assertEqual(body['tools'],[]);self.assertEqual(body['tool_choice'],'none')
        self.assertIn('does NOT approve the rejected CTO plan',note)

    def test_parent_routes_engineering_request_only_to_enabled_independent_assessment(self):
        from broker import calibration_objection_runtime as parent
        parent.initialize(self.con)
        self.con.execute('INSERT INTO calibration_objections VALUES(?,?,?,?)',
            (self.c['issue_id'],self.c['author_task'],json.dumps(self.original),json.dumps(self.parent)))
        step=Mock(side_effect=lambda con,cfg,s:s)
        fx=SimpleNamespace(capability_enabled=lambda:True,capability_step=step)
        parent.advance(self.con,self.c['issue_id'],self.c['author_task'],fx)
        step.assert_called_once()
        step.reset_mock();fx.capability_enabled=lambda:False
        parent.advance(self.con,self.c['issue_id'],self.c['author_task'],fx)
        step.assert_not_called()

    def test_diagnostic_admission_reauthenticates_native_review_and_keeps_full_read_scope(self):
        self.waiting();state=self.complete();diagnostic=review.diagnostic_configuration(self.cfg,state)
        @contextlib.contextmanager
        def db():yield self.con
        b=SimpleNamespace(db=db)
        fx=SimpleNamespace(verify=Mock(),measure=Mock(return_value=self.job),
            decision=Mock(return_value=state['decision']))
        with patch.object(review,'Effects',return_value=fx):
            review.verify_diagnostic(b,diagnostic)
            fx.verify.assert_called_once();fx.measure.assert_called_once();fx.decision.assert_called_once()
            changed=copy.deepcopy(diagnostic);changed['capability_admission']['required_paths'].append('/evidence/candidate/foreign.py')
            with self.assertRaises(ValueError):review.verify_diagnostic(b,changed)
            fx.decision.return_value={**state['decision'],'task_id':'obsolete'}
            with self.assertRaises(ValueError):review.verify_diagnostic(b,diagnostic)

    def test_native_authority_survives_only_exact_diagnostic_descendant_not_arbitrary_completion(self):
        from broker import calibration_objection_runtime as parent
        parent.initialize(self.con)
        self.con.execute('INSERT INTO calibration_objections VALUES(?,?,?,?)',
            (self.c['issue_id'],self.c['author_task'],json.dumps(self.original),json.dumps(self.parent)))
        @contextlib.contextmanager
        def db():yield self.con
        request=self.cfg['capability_request']
        fx=SimpleNamespace(b=SimpleNamespace(db=db),plans=SimpleNamespace(task=Mock(return_value={'id':request['task_id']})),
            parent=SimpleNamespace(verify=Mock(),verify_decision=Mock(),experiment_decision=Mock(return_value=request)))
        with patch.dict('os.environ',{'BROKER_REFERENCE_CAPABILITY_PROBE_IMAGE':self.cfg['image']}):
            review.Effects.verify(fx,self.cfg)
            descendant={**self.parent,'stage':'resume_pending','diagnostic_referral':{'bound':'receipt'},
                'control_diagnostic':{'stage':'referred'}}
            self.con.execute('UPDATE calibration_objections SET state=?',(json.dumps(descendant),))
            review.Effects.verify(fx,self.cfg)
            self.con.execute('UPDATE calibration_objections SET state=?',(json.dumps({**descendant,'stage':'HOMOLOGADA'}),))
            with self.assertRaises(ValueError):review.Effects.verify(fx,self.cfg)

    def test_metadata_publication_failure_does_not_block_diagnostic_progress(self):
        from broker import calibration_objection_runtime as parent,calibration_controls_diagnostic as diagnostic,handoff_runtime
        self.waiting();self.complete();parent.initialize(self.con)
        self.con.execute('INSERT INTO calibration_objections VALUES(?,?,?,?)',
            (self.c['issue_id'],self.c['author_task'],json.dumps(self.original),json.dumps(self.parent)))
        @contextlib.contextmanager
        def db():yield self.con
        with patch.dict('os.environ',{'BROKER_REFERENCE_CAPABILITY_PROBE_IMAGE':self.cfg['image']}),\
                patch.object(review,'Effects',return_value=self.fx),\
                patch.object(diagnostic,'handle_config') as step,\
                patch.object(handoff_runtime,'publish',side_effect=RuntimeError('UI unavailable')):
            result=review.handle(SimpleNamespace(db=db),self.con,self.original,self.parent)
            step.assert_called_once()
            self.assertEqual(result['capability_review']['stage'],'permitted')
            self.assertEqual(self.con.execute('SELECT category FROM calibration_capability_publication_errors').fetchone()[0],'RuntimeError')

    def test_registration_conflict_is_visible_once_and_never_retried_identically(self):
        from broker import calibration_objection_runtime as parent,calibration_controls_diagnostic as diagnostic
        self.waiting();self.complete();parent.initialize(self.con)
        self.con.execute('INSERT INTO calibration_objections VALUES(?,?,?,?)',
            (self.c['issue_id'],self.c['author_task'],json.dumps(self.original),json.dumps(self.parent)))
        @contextlib.contextmanager
        def db():yield self.con
        with patch.dict('os.environ',{'BROKER_REFERENCE_CAPABILITY_PROBE_IMAGE':self.cfg['image']}),\
                patch.object(review,'Effects',return_value=self.fx),\
                patch.object(diagnostic,'handle_config',side_effect=ValueError('immutable conflict')) as step:
            result=review.handle(SimpleNamespace(db=db),self.con,self.original,self.parent)
            self.assertEqual(result['capability_review']['category'],'capability_registration_rejected')
            review.handle(SimpleNamespace(db=db),self.con,self.original,result)
            step.assert_called_once()
            self.assertEqual(self.con.execute('SELECT count(*) FROM calibration_capability_reviews').fetchone()[0],1)
