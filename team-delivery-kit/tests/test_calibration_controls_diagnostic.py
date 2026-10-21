import copy
import json
import sqlite3
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from broker import calibration_controls_diagnostic as runtime
from generic_harness_calibration import digest


class ControlsDiagnosticTests(unittest.TestCase):
    def test_capability_admission_keeps_dependency_reads_and_names_reference_code_semantics(self):
        cfg=copy.deepcopy(self.cfg);cfg.pop('plan_evidence')
        paths=['/evidence/candidate/app/app.js','/evidence/candidate/app/index.html',
            '/evidence/candidate/tests/test.py','/evidence/previous/tests/test.py']
        cfg['capability_admission']=dict(operation='reference_capability_diagnostic_v1',required_paths=paths,
            receipt_sha256='a'*64,decision={'actual':'independent'})
        self.assertEqual(runtime.producer_context(cfg)['required_paths'],paths)
        note=runtime.instruction(cfg,{},'producer')
        self.assertLessEqual(len(note),3800)
        self.assertIn('a positive may implement missing behavior',note)
        self.assertEqual(runtime.wire.request(dict(messages=[dict(role='user',content=note)])),runtime.producer_context(cfg))
        self.assertEqual(runtime.producer_context(self.cfg)['required_paths'],
            ['/evidence/candidate/tests/test.py','/evidence/previous/tests/test.py'])

    def test_capability_diagnostic_cannot_use_legacy_plan_review_as_its_authority(self):
        from broker import calibration_capability_review as capability
        cfg=copy.deepcopy(self.cfg);cfg.pop('plan_evidence');cfg['capability_admission']={'new':'receipt'}
        b=object()
        with patch.object(capability,'verify_diagnostic') as verify:
            runtime.Effects.verify(SimpleNamespace(b=b),cfg)
            verify.assert_called_once_with(b,cfg)

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

    def failure_proof(self):
        import structured_rejection_receipts as receipts
        receipt=receipts.from_event(dict(event='model_proxy_request',status=502,category='structured_decision_response_invalid',
            execution_id='11111111-1111-4111-8111-111111111111',call_number=1,structured_rejection_category='calibration_response_invalid',
            structured_rejection_diagnostic=dict(version='calibration-constraint-v2',category='invalid_json',failure_code='invalid_json',
                constraints=[],fields=[],missing_fields=[],upstream_sha256='d'*64)))
        return dict(operation='diagnostic_producer_transport_failure_v1',task_id='producer-task',execution_id=receipt['execution_id'],
            wakeup_id='producer-wake',diagnostic_sha256=digest(self.cfg),source_sha256=digest(self.c),binding_closed=True,
            receipt=receipt,initial_transport=None,execution_authorized=False,delivery_approval=False)

    def protocol(self):
        p=runtime.transport_probe
        return dict(protocol='diagnostic_control_data_carrier_v1',proxy_image='sha256:'+'c'*64,
            probe=dict(operation='fixed_diagnostic_control_transport_v1',protocol='diagnostic_control_data_carrier_v1',passed=True,
                sources=p.source_hashes(),checks={k:True for k in p.CHECKS},model_calls=0,product_tests_executed=False,
                historical_cause_proven=False,author_retry_authorized=False,execution_authorized=False,delivery_approval=False))

    def test_proved_invalid_json_can_get_one_different_qualified_transport_not_an_identical_retry(self):
        self.advance();self.advance();self.completed('producer');self.runs[0]['status']='failed'
        self.fx.native_failure=lambda *_:self.failure_proof();self.fx.transport=lambda:self.protocol()
        s=self.advance();self.assertEqual(s['stage'],'producer_dispatch');self.assertEqual(s['transport_recovery']['attempt_limit'],1)
        self.assertIn(runtime.transport.MARKER,runtime.instruction(self.cfg,s,'producer'))
        self.advance();wakes=[x for x in self.calls if x[0]=='wake'];self.assertNotEqual(wakes[0][3],wakes[1][3])
        s=self.advance();self.assertEqual(s['category'],'diagnostic_protocol_recovery_exhausted')
        self.assertFalse(s['author_restarted']);before=list(self.calls);self.advance();self.assertEqual(self.calls,before)

    def test_already_selected_transport_or_foreign_receipt_cannot_create_a_recovery(self):
        for variant in ('selected','foreign'):
            sample=ControlsDiagnosticTests();sample.setUp();self.addCleanup(sample.doCleanups)
            sample.advance();sample.advance();sample.completed('producer');sample.runs[0]['status']='failed'
            proof=sample.failure_proof()
            if variant=='selected':proof['initial_transport']={'already':'selected'}
            else:proof['receipt']['execution_id']='22222222-2222-4222-8222-222222222222'
            sample.fx.native_failure=lambda *_:proof;sample.fx.transport=lambda:sample.protocol()
            s=sample.advance();self.assertEqual(s['stage'],'blocked');self.assertNotIn('transport_recovery',s)

    def test_legacy_failed_task_is_reclassified_from_its_actual_receipt_without_resetting_it(self):
        self.advance();self.advance();self.completed('producer');self.runs[0]['status']='failed'
        cfg,s=map(json.loads,self.con.execute('SELECT config,state FROM calibration_control_experiments').fetchone())
        s.update(stage='blocked',category='diagnostic_evidence_rejected')
        self.con.execute('UPDATE calibration_control_experiments SET state=?',(json.dumps(s),));self.con.commit()
        self.fx.native_failure=lambda *_:self.failure_proof();self.fx.transport=lambda:self.protocol()
        s=self.advance();self.assertEqual(s['stage'],'producer_dispatch');self.assertEqual(s['native_failure']['task_id'],'producer-task')
        self.assertEqual(len([x for x in self.calls if x[0]=='wake']),1)

    def test_worker_arriving_before_lost_wakeup_ack_is_authorized_by_observed_exact_intent(self):
        self.advance();self.uncertain=True;self.advance()
        task=dict(id='producer-task',agent_id='cto',issue_id='spike',wakeup_id='producer-wake')
        b=SimpleNamespace(db=lambda:self.con);note=runtime.wire.capsule(runtime.producer_context(self.cfg))
        with patch.object(runtime,'Effects',return_value=self.fx),patch.object(runtime.time,'time',return_value=2):
            self.assertEqual(runtime.prompt_contract(b,'spike',task,note),runtime.producer_context(self.cfg))
        state=json.loads(self.con.execute('SELECT state FROM calibration_control_experiments').fetchone()[0])
        self.assertEqual(state['stage'],'producer_wait');self.assertEqual(state['phase_started'],1)
        self.assertEqual([x[2] for x in self.calls if x[0]=='wake'],[True,False])

    def test_foreign_worker_cannot_turn_an_unacknowledged_intent_into_permission(self):
        self.advance();self.uncertain=True;self.advance()
        task=dict(id='producer-task',agent_id='cto',issue_id='spike',wakeup_id='foreign-wake')
        b=SimpleNamespace(db=lambda:self.con);note=runtime.wire.capsule(runtime.producer_context(self.cfg))
        with patch.object(runtime,'Effects',return_value=self.fx),patch.object(runtime.time,'time',return_value=2):
            with self.assertRaises(ValueError):runtime.prompt_contract(b,'spike',task,note)
        state=json.loads(self.con.execute('SELECT state FROM calibration_control_experiments').fetchone()[0])
        self.assertEqual(state['stage'],'producer_observe')

    def objection(self):
        return dict(operation='diagnostic_control_objection_v1',reason='Candidate lacks the required behavior',
            producer={'task_id':'producer-task','wakeup_id':'producer-wake'},execution_authorized=False,delivery_approval=False)

    def reach_objection_review(self):
        self.advance();self.advance();self.completed('producer')
        self.fx.collect=lambda *_:self.objection()
        return self.advance()

    def test_native_objection_is_reviewed_before_one_corrected_reference_proposal(self):
        s=self.reach_objection_review()
        self.assertEqual(s['stage'],'review_dispatch');self.assertEqual(s['review_subject'],'control_objection')
        self.assertIn('not measured results',runtime.instruction(self.cfg,s,'review'))
        self.advance();self.completed('review');s=self.advance()
        self.assertEqual(s['stage'],'producer_dispatch');self.assertEqual(s['control_revision']['attempt_limit'],1)
        self.assertIn('reference programs',runtime.instruction(self.cfg,s,'producer'))
        self.assertFalse(s['author_restarted']);self.assertNotIn(('measure',),self.calls)
        # A second substantive objection cannot grant itself another revision.
        self.advance();self.completed('producer');s=self.advance()
        self.assertEqual(s['category'],'diagnostic_control_revision_exhausted')
        before=list(self.calls);self.advance();self.assertEqual(self.calls,before)

    def test_independent_hold_or_objection_drift_cannot_rearm_control_construction(self):
        self.reach_objection_review();self.advance();self.completed('review');self.review='retain_technical_hold'
        s=self.advance();self.assertEqual(s['category'],'diagnostic_objection_review_hold')
        self.assertNotIn('control_revision',s)

    def test_legacy_native_objection_is_authenticated_not_blindly_reclassified(self):
        s=self.reach_objection_review();s.update(stage='blocked',category='diagnostic_native_objection')
        self.con.execute('UPDATE calibration_control_experiments SET state=?',(json.dumps(s),));self.con.commit()
        self.fx.collect=lambda *_:{**self.objection(),'reason':'changed evidence'}
        s=self.advance();self.assertEqual(s['category'],'diagnostic_evidence_rejected')
        self.assertNotIn('control_revision',s)

    def test_revision_sponsorship_is_reverified_and_cannot_survive_changed_native_evidence(self):
        self.reach_objection_review();self.advance();self.completed('review');self.advance()
        self.fx.collect=lambda *_:{**self.objection(),'reason':'changed evidence'}
        before=list(self.calls);s=self.advance()
        self.assertEqual(s['stage'],'blocked');self.assertEqual(self.calls,before)

    def test_independent_objection_reviewer_gets_no_author_workspace_mounts(self):
        self.reach_objection_review();self.advance();b=SimpleNamespace(db=lambda:self.con)
        self.assertEqual(runtime.mounts(b,dict(issue_id='spike',agent_id='lead')),[])
        with self.assertRaises(ValueError):runtime.mounts(b,dict(issue_id='spike',agent_id='cto'))
