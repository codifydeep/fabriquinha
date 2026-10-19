import copy
import json
import sqlite3
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from broker import literal_maintenance_workflow as flow


class LiteralWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.con=sqlite3.connect(':memory:');self.con.row_factory=sqlite3.Row;self.addCleanup(self.con.close)
        self.cfg={'source':{'author_task':'source','issue_id':'parent','criteria':{'A01':'unchanged'}},
            'author':'author','cto':'cto','reviewer':'lead','parent_issue_id':'diagnostic',
            'test_path':'tests/test.py','literal':'NODE_HARNESS','counterexample':{'receipt':'bound',
                'facts':{'assertion_bindings':dict(initial_expected=1,poll_minimum=3,stale_expected='Newest matching: #11')}}}
        flow.register(self.con,self.cfg);self.calls=[];self.tasks=[];self.timeout=False;self.choice='refer_to_cto';self.review_choice='approve_test_revision';parent=self
        class Effects:
            def verify(_,c):parent.assertEqual(c,parent.cfg)
            def reserve(_):return True
            def issue(_,c,first):parent.calls.append(('issue',first));return {'id':'maintenance','identifier':'TEST-1'}
            def wake(_,c,s,phase,first):
                parent.calls.append(('wake',phase,first,s['marker']))
                if parent.timeout:parent.timeout=False;raise TimeoutError()
                return {'id':phase+'-'+str(s.get('revision',0))}
            def runs(_,c,s):return parent.tasks
            def decision(_,c,s,phase,t):
                if phase in ('plan','diagnose'):value={'action':'request_test_revision','reason':'Preserve assertions; repair driver','optional_files':[]}
                elif phase=='review':value={'action':parent.review_choice,'reason':'Measured selective driver, unchanged assertions','optional_files':[], 'manifest_sha256':s['inspection']['candidate_manifest_sha256']}
                else:value={**flow.review_context(c,s,phase),'action':parent.choice,'reason':'Evidence justifies scoped author proposal',
                    'author_retry_authorized':False,'execution_authorized':False,'delivery_approval':False}
                return {'task_id':t['id'],'agent_id':t['agent_id'],'wakeup_id':t['wakeup_id'],'value':value}
            def prepare(_,c,s):parent.calls.append(('prepare',));return {'issue_base':'qualified','seed':'frozen'}
            def snapshot(_,c,s,t):return {'volume':'new-frozen','task_id':t['id']}
            def inspect(_,c,s):return {'candidate_manifest_sha256':'a'*64,'stale_witness_selectivity_passed':True,
                'reports':{'guarded':dict(initial_requests=1,poll_requests=3,stale_guard_text='Newest matching: #11'),
                    'unguarded':dict(initial_requests=1,poll_requests=3,stale_guard_text='Newest matching: #4')},
                'non_target_files_unchanged':True,'structure':{'outside_literal_bytes_preserved':True}}
            def validate_inspection(_,c,s,r):parent.assertTrue(r['non_target_files_unchanged'])
            def preserved_submission(_,c,s):parent.calls.append(('preserved',s['author_task']))
            def reseed(_,c,s):parent.calls.append(('reseed',s['history'][-1]['author_task']));return {'seed':'exact-rejected-artifact'}
        self.fx=Effects();self.experiment_supported=True
        def experiment(c,s):
            self.calls.append(('experiment',s['diagnosis']['task_id']))
            reports={name:{driver:dict(initial_requests=1,poll_requests=3 if name=='before_capture' else 2,
                stale_guard_text='Newest matching: #11' if driver=='guarded' else 'Newest matching: #4')
                for driver in ('guarded','unguarded')} for name in ('original','before_capture','after_capture')}
            return dict(hypothesis_supported=self.experiment_supported,reports=reports,
                assertion_bindings=dict(initial_expected=1,poll_minimum=3,stale_expected='Newest matching: #11'))
        self.fx.experiment=experiment;self.fx.validate_experiment=lambda *args:None
        decision=self.fx.decision;recorded={}
        def immutable_decision(c,s,p,t):
            if t['id'] not in recorded:recorded[t['id']]=decision(c,s,p,t)
            return copy.deepcopy(recorded[t['id']])
        self.fx.decision=immutable_decision

    def advance(self,now=1):return flow.advance(self.con,'source',self.fx,now=now)
    def complete(self,phase,revision=0):
        actor={'triage':'lead','plan':'cto','permit':'lead','author':'author','review':'lead','diagnose':'cto','sponsor':'lead'}[phase]
        self.tasks.append({'id':phase+'-task-'+str(revision),'agent_id':actor,'issue_id':'maintenance',
            'status':'completed','wakeup_id':phase+'-'+str(revision)})

    def reach_author(self):
        self.advance()
        for phase in ('triage','plan','permit'):
            self.advance();self.complete(phase);self.advance()
        self.assertEqual(self.advance()['stage'],'author_dispatch')

    def test_full_separate_maintenance_requires_two_authorities_then_actual_inspection_and_independent_review(self):
        self.reach_author();self.assertIn(('prepare',),self.calls)
        self.advance();self.complete('author');self.advance();self.advance();s=self.advance()
        self.assertEqual(s['stage'],'review_dispatch')
        self.advance();self.complete('review');s=self.advance()
        self.assertEqual(s['stage'],'maintenance_approved');self.assertFalse(s['delivery_approval'])
        self.assertFalse(s['source_reset']);self.assertFalse(s['functional_red'])

    def test_cto_scope_proposal_preflights_actual_typed_contract_without_findings_diagnosis(self):
        self.assertEqual(len(flow.preflight_plan(self.cfg,{})),64)
        actual=flow.instruction(self.cfg,{},'plan')
        with patch.object(flow,'instruction',return_value=actual+'\nDELIVERY_TYPED_TEST_DIAGNOSIS_V1\n'):
            with self.assertRaises(ValueError):flow.preflight_plan(self.cfg,{})

    def test_rejected_preparation_preserves_phase_and_hash_without_leaking_error_text(self):
        import hashlib
        self.advance()
        for phase in ('triage','plan','permit'):
            self.advance();self.complete(phase);self.advance()
        with patch.object(self.fx,'prepare',side_effect=ValueError('private diagnostic detail')):
            state=self.advance()
        self.assertEqual(state['stage'],'blocked')
        self.assertEqual(state['last_error'],dict(phase='prepare',type='ValueError',
            sha256=hashlib.sha256(b'private diagnostic detail').hexdigest()))
        self.assertNotIn('private diagnostic detail',json.dumps(state))
        self.assertEqual(set(state['decisions']),{'triage','plan','permit'})

    def test_unknown_wakeup_ack_only_observes_same_intent_and_deadline(self):
        self.advance();self.timeout=True;self.advance();self.advance()
        wakes=[c for c in self.calls if c[0]=='wake'];self.assertEqual([c[2] for c in wakes],[True,False])
        self.assertEqual(wakes[0][3],wakes[1][3])

    def test_foreign_actor_or_wakeup_cannot_authorize_writes(self):
        self.advance();self.advance();self.complete('triage');self.tasks[-1]['agent_id']='author'
        self.assertEqual(self.advance()['stage'],'blocked');self.assertNotIn(('prepare',),self.calls)

    def test_independent_hold_never_dispatches_author_or_resets_original(self):
        self.advance();self.advance();self.complete('triage');self.choice='retain_technical_hold'
        s=self.advance();self.assertEqual(s['stage'],'blocked');before=copy.deepcopy(self.calls)
        self.advance();self.assertEqual(before,self.calls);self.assertNotIn(('prepare',),self.calls)

    def test_native_failure_and_expired_queue_are_not_success_or_automatic_retry(self):
        self.advance();self.advance();self.complete('triage');self.tasks[-1]['status']='failed'
        s=self.advance();self.assertEqual(s['category'],'native_triage_failed')
        sample=LiteralWorkflowTests();sample.setUp();self.addCleanup(sample.doCleanups);sample.advance();sample.advance()
        self.assertEqual(sample.advance(now=1802)['category'],'native_triage_deadline')

    def test_new_config_cannot_rearm_consumed_maintenance_budget(self):
        with self.assertRaises(ValueError):flow.register(self.con,{**self.cfg,'literal':'OTHER'})

    def failed_poll_review(self):
        self.reach_author();self.advance();self.complete('author');self.advance()
        real=self.fx.inspect
        def failed(*args):
            value=real(*args);value['stale_witness_selectivity_passed']=False
            for report in value['reports'].values():report['poll_requests']=2
            return value
        self.fx.inspect=failed
        self.advance();s=self.advance();self.assertEqual(s['stage'],'review_dispatch');return s

    def test_failed_protocol_reaches_changes_only_review_never_source_adoption_or_approval(self):
        s=self.failed_poll_review();note=flow.instruction(self.cfg,s,'review')
        self.assertIn('approval is forbidden',note);self.assertIn('"stale_ordering_passed": true',note)
        self.assertIn('"poll_requests_passed": false',note)
        self.advance();self.complete('review');s=self.advance()
        self.assertEqual(s['category'],'maintenance_review_conflicts_fixed_gate')
        self.assertFalse(s['delivery_approval']);self.assertNotIn(('reseed',),self.calls)

    def test_failed_protocol_changes_request_returns_to_original_author_with_facts_preserved(self):
        self.failed_poll_review();self.review_choice='reject_test_revision'
        self.advance();self.complete('review');s=self.advance()
        self.assertEqual(s['stage'],'reseed');self.assertEqual(s['revision'],1)
        self.assertFalse(s['history'][-1]['inspection']['stale_witness_selectivity_passed'])
        note=flow.instruction(self.cfg,s,'author')
        self.assertIn('preserve already-passing behavior',note);self.assertIn('"minimum_poll_requests": 3',note)

    def test_self_review_is_refused_at_registration(self):
        con=sqlite3.connect(':memory:');self.addCleanup(con.close)
        with self.assertRaises(ValueError):flow.register(con,{**self.cfg,'reviewer':'author'})

    def submit_for_review(self,revision=0):
        self.advance();self.complete('author',revision);self.advance();self.advance();self.advance();self.advance();self.complete('review',revision)

    def test_requested_changes_return_to_same_author_once_and_preserve_both_rejected_revisions(self):
        self.reach_author();self.submit_for_review();self.review_choice='reject_test_revision'
        s=self.advance();self.assertEqual(s['stage'],'reseed');self.assertEqual(s['history'][0]['author_task'],'author-task-0')
        self.advance();self.submit_for_review(1);s=self.advance()
        self.assertEqual(s['category'],'maintenance_review_revision_exhausted');self.assertEqual(len(s['history']),2)
        self.assertFalse(s['source_reset']);self.assertEqual(self.advance()['stage'],'diagnose_dispatch')

    def exhausted(self):
        self.reach_author();self.submit_for_review();self.review_choice='reject_test_revision';self.advance()
        self.advance();self.submit_for_review(1);self.advance()

    def test_exhaustion_wakes_cto_once_then_preserves_diagnosis_without_third_author_or_approval(self):
        self.exhausted();s=self.advance();self.assertEqual(s['stage'],'diagnose_dispatch')
        self.assertEqual(s['owner'],'cto');self.assertEqual(s['cto_escalation']['attempt_limit'],1)
        self.assertFalse(s['cto_escalation']['author_retry_authorized'])
        self.assertEqual(len([x for x in self.calls if x[0]=='preserved']),2)
        self.advance();self.complete('diagnose',1);s=self.advance()
        self.assertEqual(s['category'],'maintenance_cto_experiment_required')
        self.assertEqual(s['diagnosis']['agent_id'],'cto');self.assertEqual(len(s['history']),2)
        self.assertEqual(self.advance()['stage'],'capture_experiment')
        self.assertFalse(s['delivery_approval']);self.assertFalse(s['functional_red'])
        self.assertEqual(len([x for x in self.calls if x[:2]==('wake','author')]),2)

    def test_cto_diagnosis_uses_readonly_typed_contract_and_does_not_inherit_reviewer_authority(self):
        self.exhausted();s=self.advance();note=flow.instruction(self.cfg,s,'diagnose')
        self.assertIn('not necessarily correct',note);self.assertIn('No edits, shell, tests',note)
        self.assertIn('Neither action authorizes another author attempt',note)
        self.assertIn('DELIVERY_REVIEW_READ_PATH:/evidence/candidate/tests/test.py',note)
        self.assertEqual(len(flow.preflight_plan(self.cfg,s,'diagnose')),64)
        self.assertNotIn('DELIVERY_TYPED_REVIEW_V1',note)

    def test_historical_rejection_or_artifact_drift_blocks_cto_dispatch(self):
        self.exhausted()
        with patch.object(self.fx,'preserved_submission',side_effect=ValueError('changed frozen artifact')):
            state=self.advance()
        self.assertEqual(state['category'],'maintenance_evidence_rejected')
        self.assertNotIn('cto_escalation',state)
        self.assertFalse(any(x[:2]==('wake','diagnose') for x in self.calls))

    def test_unknown_cto_wakeup_ack_only_observes_same_intent_after_restart(self):
        self.exhausted();self.advance();self.timeout=True;self.advance();s=self.advance()
        wakes=[x for x in self.calls if x[:2]==('wake','diagnose')]
        self.assertEqual([x[2] for x in wakes],[True,False]);self.assertEqual(wakes[0][3],wakes[1][3])
        self.assertEqual(s['stage'],'diagnose_wait')

    def test_cto_cannot_return_review_approval_or_reset_historical_attempts(self):
        self.exhausted();self.advance();self.advance();self.complete('diagnose',1)
        original=self.fx.decision
        def invalid(c,s,p,t):
            receipt=original(c,s,p,t)
            if p=='diagnose':receipt['value']['action']='approve_test_revision'
            return receipt
        self.fx.decision=invalid;state=self.advance()
        self.assertEqual(state['category'],'maintenance_evidence_rejected');self.assertEqual(len(state['history']),2)

    def diagnosed(self):
        self.exhausted();self.advance();self.advance();self.complete('diagnose',1);self.advance()

    def sponsored(self):
        self.diagnosed();self.advance();s=self.advance();self.assertEqual(s['stage'],'sponsor_dispatch')
        self.advance();self.complete('sponsor',1);return self.advance()

    def test_executed_new_evidence_and_independent_sponsor_earn_exactly_one_additional_correction(self):
        s=self.sponsored();self.assertEqual(s['stage'],'reseed');self.assertEqual(s['revision'],2)
        self.assertEqual(s['repair_authorization']['additional_submission_limit'],1)
        self.assertFalse(s['source_reset']);self.assertEqual(len(s['history']),2)
        note=flow.instruction(self.cfg,s,'author');self.assertIn('Only the before-capture placement',note)
        self.advance();self.review_choice='approve_test_revision';self.submit_for_review(2);s=self.advance()
        self.assertEqual(s['stage'],'maintenance_approved');self.assertFalse(s['delivery_approval'])
        self.assertEqual(len([x for x in self.calls if x[:2]==('wake','author')]),3)
        self.assertEqual(len([x for x in self.calls if x[0]=='experiment']),1)

    def test_unsupported_experiment_or_independent_hold_never_earns_extra_author_attempt(self):
        self.diagnosed();self.experiment_supported=False;self.advance();s=self.advance()
        self.assertEqual(s['category'],'maintenance_capture_hypothesis_unsupported')
        self.assertNotIn('repair_authorization',s)
        sample=LiteralWorkflowTests();sample.setUp();self.addCleanup(sample.doCleanups)
        sample.diagnosed();sample.advance();sample.advance();sample.advance();sample.complete('sponsor',1)
        sample.choice='retain_technical_hold';s=sample.advance()
        self.assertEqual(s['category'],'maintenance_sponsor_hold');self.assertNotIn('repair_authorization',s)

    def test_third_rejection_preserves_all_deliveries_without_second_cto_or_budget_reset(self):
        self.sponsored();self.advance();self.submit_for_review(2);s=self.advance()
        self.assertEqual(s['category'],'maintenance_evidence_replan_rejected');self.assertEqual(len(s['history']),3)
        before=list(self.calls);self.advance();self.assertEqual(self.calls,before)
        self.assertFalse(s['source_reset']);self.assertEqual(s['revision'],2)

    def test_drifted_sponsorship_cannot_authorize_reseed_or_author(self):
        self.sponsored();row=self.con.execute('SELECT state FROM literal_maintenance_workflows').fetchone()
        s=json.loads(row[0]);s['repair_authorization']['additional_submission_limit']=2
        self.con.execute('UPDATE literal_maintenance_workflows SET state=?',(json.dumps(s),))
        s=self.advance();self.assertEqual(s['category'],'maintenance_evidence_rejected')
        self.assertEqual(len([x for x in self.calls if x[:2]==('wake','author')]),2)

    def test_drifted_native_scope_does_not_survive_until_preparation(self):
        self.advance()
        for phase in ('triage','plan','permit'):
            self.advance();self.complete(phase);self.advance()
        original=self.fx.decision
        def drift(cfg,s,phase,task):
            value=original(cfg,s,phase,task)
            if phase=='plan':value['value']['reason']='different scope'
            return value
        self.fx.decision=drift;s=self.advance();self.assertEqual(s['stage'],'blocked');self.assertNotIn(('prepare',),self.calls)

    def test_invalid_native_schema_is_recorded_as_owned_hold_not_an_uncaught_tick_error(self):
        self.advance();self.advance();self.complete('triage');original=self.fx.decision
        self.fx.decision=lambda *args:{**original(*args),'value':{**original(*args)['value'],'execution_authorized':True}}
        s=self.advance();self.assertEqual(s['category'],'maintenance_evidence_rejected');self.assertEqual(s['owner'],'cto')
