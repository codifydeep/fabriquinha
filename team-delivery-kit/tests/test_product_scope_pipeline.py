import json
import unittest
from unittest.mock import patch
import test_product_scope_bootstrap as fixtures
from broker import product_scope_pipeline as pipeline, adapted_test_review


class ProductScopePipelineTests(unittest.TestCase):
    def setUp(self):
        f=fixtures.ProductScopeBootstrapTests();f.setUp();self.addCleanup(f.doCleanups)
        self.b=f.b;self.context=f.context
        self.issue='00000000-0000-4000-8000-000000000001'
        with self.b.db() as con:
            con.execute('UPDATE delivery_routes SET issue_id=?',(self.issue,))
            con.execute('UPDATE delivery_handoffs SET issue_id=?',(self.issue,))
        self.config=dict(issue_id=self.issue,contract_sha256=self.context['contract_sha256'],enabled=True)

    def state(self):
        with self.b.db() as con:
            return json.loads(con.execute('SELECT state FROM product_scope_runs WHERE issue_id=?',(self.issue,)).fetchone()[0])

    def tick(self):
        with patch.object(pipeline.controller_maintenance,'current',return_value=None):return pipeline.tick(self.b)

    def test_unregistered_pipeline_leaves_legacy_untouched(self):
        self.assertEqual(self.tick(),set())

    def test_registration_is_explicit_immutable_and_has_no_authority(self):
        pipeline.register(self.b,self.config)
        self.assertEqual(self.state()['stage'],'waiting_for_hold')
        self.assertFalse(self.state()['delivery_approval'])
        with self.assertRaises(ValueError):pipeline.register(self.b,dict(self.config,contract_sha256='0'*64))
        pipeline.register(self.b,dict(self.config,enabled=False))
        self.assertEqual(self.tick(),set())

    def test_selects_exact_hold_and_owns_it_before_external_effects(self):
        pipeline.register(self.b,self.config)
        with patch.object(pipeline.bootstrap,'prepare') as prepare:
            self.assertEqual(self.tick(),{self.issue});prepare.assert_not_called()
        self.assertEqual(self.state()['source_task'],'source')
        self.assertEqual(self.state()['failure_output_sha256'],self.context['failure_output_sha256'])

    def test_pending_job_survives_restart_and_reobserves_same_issue(self):
        pipeline.register(self.b,self.config);self.tick()
        with patch.object(pipeline.bootstrap,'prepare',side_effect=pipeline.validation_job.Pending('existing job')) as prepare:
            before=self.state();self.tick();self.tick()
            self.assertEqual(self.state(),before)
            self.assertEqual(prepare.call_args_list[0],prepare.call_args_list[1])

    def test_changed_sponsor_blocks_without_identical_retry(self):
        pipeline.register(self.b,self.config);self.tick()
        with self.b.db() as con:con.execute('UPDATE delivery_handoffs SET source_task=?',('other',))
        with patch.object(pipeline.bootstrap,'prepare') as prepare:
            self.assertEqual(self.tick(),{self.issue});self.tick();prepare.assert_not_called()
        self.assertEqual(self.state()['stage'],'blocked')
        self.assertFalse(self.state()['incident']['automatic_retry'])

    def test_maintenance_and_paused_active_route_retain_ownership(self):
        pipeline.register(self.b,self.config);self.tick()
        pipeline.register(self.b,dict(self.config,enabled=False))
        with patch.object(pipeline.bootstrap,'prepare') as prepare:
            self.assertEqual(self.tick(),{self.issue});prepare.assert_not_called()
        with patch.object(pipeline.controller_maintenance,'current',return_value={'stage':'sealed'}):
            self.assertEqual(pipeline.tick(self.b),{self.issue})

    def test_unknown_wakeup_ack_does_not_clear_intent_or_claim_delivery(self):
        pipeline.register(self.b,self.config);self.tick()
        before=self.state()
        with patch.object(pipeline.bootstrap,'prepare',side_effect=TimeoutError()):self.tick()
        self.assertEqual(self.state(),before)
        self.assertFalse(self.state()['delivery_approval'])

    def test_nonfunctional_hold_remains_with_legacy(self):
        pipeline.register(self.b,self.config)
        with self.b.db() as con:con.execute('UPDATE delivery_handoffs SET data=?',(json.dumps(dict(validation_failure=dict(category='missing_evidence'))),))
        self.assertEqual(self.tick(),set())
        self.assertEqual(self.state()['stage'],'waiting_for_hold')

    def plan_state(self):
        pipeline.register(self.b,self.config);self.tick()
        before=self.state()
        pipeline.save(self.b,self.issue,before,dict(before,stage='scope_plan',plan_key='plan'))
        context=dict(self.context,issue_id=self.issue)
        return dict(key='plan',context=context,stage='plan_approved',
                    materialization=dict(stage='complete'),registration=dict(stage='complete'))

    def test_only_admitted_author_returns_issue_to_legacy_without_delivery_success(self):
        plan=self.plan_state()
        with patch.object(pipeline.ledger,'load',return_value=plan),patch.object(pipeline.author,'tick',return_value=dict(
                plan,dispatch=dict(author=dict(stage='awaiting_task',wakeup_id='wake')))):
            self.assertEqual(self.tick(),{self.issue})
        with patch.object(pipeline.ledger,'load',return_value=plan),patch.object(pipeline.author,'tick',return_value=dict(
                plan,dispatch=dict(author=dict(stage='admitted',task_id='new-author')))):
            self.assertEqual(self.tick(),set())
        self.assertEqual(self.state()['author_task'],'new-author')
        self.assertEqual(self.state()['owner'],self.context['author'])
        self.assertFalse(self.state()['delivery_approval'])
        with patch.object(pipeline.author,'tick') as author:
            self.tick();author.assert_not_called()

    def test_planning_materialization_registration_and_author_are_ordered(self):
        plan=self.plan_state()
        for phase in ('proposal','materialization','registration','author'):
            selected=dict(plan)
            if phase=='proposal':selected['stage']='awaiting_proposal'
            if phase=='materialization':selected['materialization']={}
            if phase=='registration':selected['registration']={}
            with self.subTest(phase=phase),patch.object(pipeline.ledger,'load',return_value=selected),\
                    patch.object(pipeline.execution,'tick') as proposal,\
                    patch.object(pipeline.materialization,'tick') as materialization,\
                    patch.object(pipeline.registration,'tick') as registration,\
                    patch.object(pipeline.author,'tick',return_value=plan) as author:
                self.tick()
                for name,mock in [('proposal',proposal),('materialization',materialization),('registration',registration),('author',author)]:
                    self.assertEqual(mock.call_count,int(name==phase))

    def test_rejected_review_retains_technical_owner_without_author_dispatch(self):
        plan=self.plan_state();plan['stage']='changes_requested'
        with patch.object(pipeline.ledger,'load',return_value=plan),patch.object(pipeline.author,'tick') as author:
            self.assertEqual(self.tick(),{self.issue});author.assert_not_called()
        self.assertEqual(self.state()['incident']['owner'],self.context['cto'])

    def test_external_failure_does_not_abort_other_issue_coordination_or_leak_error_text(self):
        pipeline.register(self.b,self.config);self.tick()
        other='00000000-0000-4000-8000-000000000002'
        with self.b.db() as con:
            route=con.execute('SELECT config FROM delivery_routes').fetchone()[0]
            con.execute('INSERT INTO delivery_routes VALUES (?,?)',(other,route))
        pipeline.register(self.b,dict(self.config,issue_id=other))
        with patch.object(pipeline.bootstrap,'prepare',side_effect=OSError('private transport details')):
            self.assertEqual(self.tick(),{self.issue})
        incident=self.state()['incident']
        self.assertEqual(incident['category'],'scope_pipeline_infrastructure_failure')
        self.assertEqual(incident['phase'],'bootstrap')
        self.assertNotIn('private',json.dumps(incident))
        with self.b.db() as con:
            other_state=json.loads(con.execute('SELECT state FROM product_scope_runs WHERE issue_id=?',(other,)).fetchone()[0])
        self.assertEqual(other_state['stage'],'waiting_for_hold')

    def test_legacy_test_review_does_not_dispute_owned_issue(self):
        config=dict(issue_id=self.issue,revision_id='revision')
        with self.b.db() as con:
            con.execute('CREATE TABLE adapted_test_reviews(revision_id TEXT,config TEXT,state TEXT)')
            con.execute('INSERT INTO adapted_test_reviews VALUES (?,?,?)',('revision',json.dumps(config),json.dumps(dict(status='pending'))))
        with patch.object(adapted_test_review,'_advance') as advance:
            adapted_test_review.tick(self.b,excluded_issues={self.issue});advance.assert_not_called()
            adapted_test_review.tick(self.b);advance.assert_called_once()
