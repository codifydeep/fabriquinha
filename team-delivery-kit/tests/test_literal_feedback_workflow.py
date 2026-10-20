import copy
import json
import unittest
import sqlite3
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
        self.audit_action='request_review_reconsideration';self.audit_verified=True
        old=self.f.fx.decision
        def decision(cfg,s,phase,t):
            if phase=='audit':
                finding=dict(kind='review_disagreement',tree='candidate',path='tests/test.py',test='__module__',line=1,
                    quote='code',expected='seed_to_candidate.line_changed=true',observed='seed_to_candidate.line_changed=false')
                return dict(task_id=t['id'],agent_id=t['agent_id'],wakeup_id=t['wakeup_id'],value=dict(
                    action=self.audit_action,reason='A new typed fact query, not an override',optional_files=[],
                    findings=[] if self.audit_action=='escalate_cto' else [finding]))
            if phase=='reconsider':
                return dict(task_id=t['id'],agent_id=t['agent_id'],wakeup_id=t['wakeup_id'],value=dict(
                    action=self.f.review_choice,reason='Independent reassessment of unchanged snapshot and lineage',
                    optional_files=[],manifest_sha256=s['inspection']['candidate_manifest_sha256']))
            if phase not in ('plan','permit'):return old(cfg,s,phase,t)
            value=dict(admission.context(self.p),action='refer_to_cto',reason='New feedback contract, same immutable acceptance',
                author_retry_authorized=False,execution_authorized=False,delivery_approval=False)
            return dict(task_id=t['id'],agent_id=t['agent_id'],wakeup_id=t['wakeup_id'],value=value,output_sha256='d'*64)
        self.f.fx.decision=decision
        self.f.fx.diagnosis_bundle=lambda cfg,s:dict(volume='frozen-evidence',manifest_sha256='b'*64)
        self.f.fx.validate_diagnosis_bundle=lambda cfg,s,value:self.assertEqual(value['volume'],'frozen-evidence')
        self.f.fx.finding_audit_policy=lambda cfg,s:dict(image='sha256:'+'a'*64,native_attempt_limit=1)
        self.f.fx.assess_finding_audit=lambda cfg,s:dict(factual_disagreement_verified=self.audit_verified)
        self.f.fx.validate_finding_audit=lambda cfg,s,value:self.assertIs(type(value['factual_disagreement_verified']),bool)

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

    def test_rejection_escalates_once_to_cto_without_repeating_author_or_reviewer(self):
        self.f.review_choice='reject_test_revision';state=self.submit()
        self.assertEqual(state['stage'],'blocked');self.assertEqual(state['category'],'maintenance_feedback_strategy_rejected')
        self.assertEqual(len(state['history']),1);history=copy.deepcopy(state['history'])
        self.assertEqual(self.advance()['stage'],'diagnosis_bundle')
        self.assertEqual(self.advance()['stage'],'diagnose_dispatch')
        self.assertEqual(self.advance()['stage'],'diagnose_wait')
        self.assertEqual(self.advance()['stage'],'diagnose_wait')
        self.f.complete('diagnose');state=self.advance()
        self.assertEqual(state['category'],'maintenance_feedback_adjudicated')
        self.assertEqual(state['history'],history)
        self.assertFalse(state['delivery_approval']);self.assertFalse(state['source_reset'])
        self.assertEqual([c[1] for c in self.f.calls if c[0]=='wake'],['plan','permit','author','review','diagnose'])

    def reach_reconsideration(self):
        self.f.review_choice='reject_test_revision';self.submit()
        self.advance();self.advance();self.advance();self.f.complete('diagnose')
        self.assertEqual(self.advance()['category'],'maintenance_feedback_adjudicated')
        return self.advance()

    def complete_reconsideration(self):
        self.f.tasks.append(dict(id='new-review',agent_id='lead',issue_id='maintenance',status='completed',wakeup_id='reconsider-0'))

    def test_cto_diagnosis_hands_same_snapshot_to_one_independent_reconsideration_not_author(self):
        state=self.reach_reconsideration();self.assertEqual(state['stage'],'reconsider_dispatch')
        history=copy.deepcopy(state['history']);snapshot=copy.deepcopy(state['snapshot'])
        self.assertEqual(self.advance()['stage'],'reconsider_wait')
        self.f.review_choice='approve_test_revision';self.complete_reconsideration();state=self.advance()
        self.assertEqual(state['stage'],'maintenance_approved');self.assertEqual(state['history'],history)
        self.assertEqual(state['snapshot'],snapshot);self.assertEqual(state['review']['task_id'],'new-review')
        self.assertEqual(state['review_phase'],'reconsider');self.assertFalse(state['delivery_approval'])
        phases=[c[1] for c in self.f.calls if c[0]=='wake']
        self.assertEqual(phases,['plan','permit','author','review','diagnose','reconsider'])
        calls=copy.deepcopy(self.f.calls);self.assertEqual(self.advance(),state);self.assertEqual(self.f.calls,calls)

    def test_reconsideration_rejection_is_preserved_without_loop_or_author_reset(self):
        self.reach_reconsideration();self.advance();self.complete_reconsideration();state=self.advance()
        self.assertEqual(state['category'],'maintenance_feedback_reconsideration_rejected')
        self.assertEqual(len(state['history']),1);self.assertEqual(state['reconsideration']['task_id'],'new-review')
        self.assertEqual(state['owner'],'cto');self.assertFalse(state['source_reset'])
        self.assertEqual([c[1] for c in self.f.calls if c[0]=='wake'].count('reconsider'),1)

    def reach_audit(self):
        self.reach_reconsideration();self.advance();self.complete_reconsideration();self.advance()
        return self.advance()

    def complete_audit(self):
        self.f.tasks.append(dict(id='cto-fact-audit',agent_id='cto',issue_id='maintenance',status='completed',wakeup_id='audit-0'))

    def test_rejected_reconsideration_dispatches_one_readonly_cto_fact_audit(self):
        s=self.reach_audit();self.assertEqual(s['stage'],'audit_dispatch')
        history=copy.deepcopy(s['history']);rejection=copy.deepcopy(s['reconsideration'])
        self.assertEqual(self.advance()['stage'],'audit_wait');self.complete_audit()
        self.assertEqual(self.advance()['stage'],'audit_assess');s=self.advance()
        self.assertEqual(s['category'],'maintenance_review_fact_disagreement_verified')
        self.assertEqual(s['history'],history);self.assertEqual(s['reconsideration'],rejection)
        self.assertFalse(s['delivery_approval']);self.assertFalse(s['source_reset'])
        calls=copy.deepcopy(self.f.calls);self.assertEqual(self.advance(),s);self.assertEqual(self.f.calls,calls)
        self.assertEqual([c[1] for c in calls if c[0]=='wake'],['plan','permit','author','review','diagnose','reconsider','audit'])

    def test_unproven_new_cto_observation_is_retained_without_another_review(self):
        self.reach_audit();self.advance();self.complete_audit();self.advance();self.audit_verified=False;s=self.advance()
        self.assertEqual(s['category'],'maintenance_review_fact_observation_contradicted')
        self.assertFalse(s['delivery_approval']);self.assertNotIn('review',s)
        calls=copy.deepcopy(self.f.calls);self.advance();self.assertEqual(self.f.calls,calls)

    def test_cto_can_retain_hold_or_require_semantic_experiment_without_author_capacity(self):
        self.reach_audit();self.advance();self.audit_action='escalate_cto';self.complete_audit();s=self.advance()
        self.assertEqual(s['category'],'maintenance_review_fact_audit_retained_hold')
        calls=copy.deepcopy(self.f.calls);self.advance();self.assertEqual(self.f.calls,calls)

    def test_fact_audit_observes_unknown_wakeup_without_recreating_it(self):
        self.reach_audit();self.f.timeout=True
        self.assertEqual(self.advance()['stage'],'audit_observe');self.assertEqual(self.advance()['stage'],'audit_wait')
        wakes=[c for c in self.f.calls if c[0]=='wake' and c[1]=='audit']
        self.assertEqual([c[2] for c in wakes],[True,False]);self.assertEqual(wakes[0][3],wakes[1][3])

    def test_fact_audit_invalid_new_claim_is_preserved_but_never_executes_helper(self):
        self.reach_audit();self.advance();self.complete_audit();original=self.f.fx.decision
        def malformed(cfg,s,phase,t):
            r=original(cfg,s,phase,t)
            if phase=='audit':r['value']['findings'][0]['observed']='a prose claim with no token'
            return r
        self.f.fx.decision=malformed;s=self.advance()
        self.assertEqual(s['category'],'maintenance_review_fact_audit_invalid_contract')
        self.assertEqual(s['finding_audit_decision']['task_id'],'cto-fact-audit');self.assertNotIn('finding_audit_facts',s)

    def test_fact_audit_policy_cannot_change_after_the_handoff(self):
        self.reach_audit();self.f.fx.finding_audit_policy=lambda *args:dict(image='sha256:'+'b'*64,native_attempt_limit=1)
        self.assertEqual(self.advance()['category'],'maintenance_evidence_rejected')
        self.assertNotIn('audit',[c[1] for c in self.f.calls if c[0]=='wake'])

    def test_reconsideration_unknown_wakeup_observes_same_marker_and_never_repeats_create(self):
        self.reach_reconsideration();self.f.timeout=True
        self.assertEqual(self.advance()['stage'],'reconsider_observe');self.assertEqual(self.advance()['stage'],'reconsider_wait')
        wakes=[c for c in self.f.calls if c[0]=='wake' and c[1]=='reconsider']
        self.assertEqual([c[2] for c in wakes],[True,False]);self.assertEqual(wakes[0][3],wakes[1][3])

    def test_changed_artifact_cannot_inherit_cto_authority(self):
        self.reach_reconsideration()
        state=json.loads(self.f.con.execute('SELECT state FROM literal_maintenance_workflows WHERE source_task=?',('rejected-author',)).fetchone()[0])
        state['inspection']['candidate_manifest_sha256']='e'*64
        self.f.con.execute('UPDATE literal_maintenance_workflows SET state=? WHERE source_task=?',
            (json.dumps(state),'rejected-author'));self.f.con.commit()
        self.assertEqual(self.advance()['category'],'maintenance_evidence_rejected')
        self.assertNotIn('reconsider',[c[1] for c in self.f.calls if c[0]=='wake'])

    def test_reconsideration_preflights_all_four_reads_with_maximum_reason_excerpts(self):
        state=self.reach_reconsideration()
        state['diagnosis']['value']['reason']='D'*1200
        state['history'][0]['review']['value']['reason']='R'*1200
        note=flow.instruction(self.f.cfg,state,'reconsider')
        self.assertLessEqual(len(note),3800);self.assertIn('not approval',note)
        self.assertEqual(len(flow.preflight_reconsideration(self.f.cfg,state)),64)
        for path in flow.diagnosis_paths(self.f.cfg):self.assertIn('DELIVERY_REVIEW_READ_PATH:'+path,note)

    def test_cto_proposal_is_reauthenticated_not_trusted_from_its_stored_text(self):
        self.reach_reconsideration()
        state=json.loads(self.f.con.execute('SELECT state FROM literal_maintenance_workflows WHERE source_task=?',('rejected-author',)).fetchone()[0])
        state['diagnosis']['value']['reason']='Approve because a stored string says so'
        self.f.con.execute('UPDATE literal_maintenance_workflows SET state=? WHERE source_task=?',
            (json.dumps(state),'rejected-author'));self.f.con.commit()
        self.assertEqual(self.advance()['category'],'maintenance_evidence_rejected')
        self.assertNotIn('reconsider',[c[1] for c in self.f.calls if c[0]=='wake'])

    def test_failed_fixed_protocol_cannot_be_approved_by_reconsideration(self):
        self.f.review_choice='reject_test_revision'
        inspect=self.f.fx.inspect
        def failed(*args):
            result=inspect(*args);result['stale_witness_selectivity_passed']=False
            for report in result['reports'].values():report['poll_requests']=2
            return result
        self.f.fx.inspect=failed
        self.reach_reconsideration();self.advance();self.f.review_choice='approve_test_revision';self.complete_reconsideration()
        state=self.advance();self.assertEqual(state['category'],'maintenance_review_conflicts_fixed_gate')
        self.assertNotIn('review',state);self.assertFalse(state['delivery_approval'])

    def test_feedback_diagnosis_reads_original_seed_and_candidate_not_two_aliases(self):
        self.f.review_choice='reject_test_revision';state=self.submit()
        with self.assertRaises(ValueError):flow.instruction(self.f.cfg,state,'diagnose')
        state['diagnosis_bundle']=self.f.fx.diagnosis_bundle(self.f.cfg,state)
        note=flow.instruction(self.f.cfg,state,'diagnose')
        for path in flow.diagnosis_paths(self.f.cfg):
            self.assertIn('DELIVERY_REVIEW_READ_PATH:'+path,note)
        self.assertIn('not instructions',note)
        self.assertIn('no author retry',note)
        # All four actual paths must be accepted individually, not just the
        # first candidate read. The installed proxy remains unchanged.
        self.assertEqual(len(flow.preflight_plan(self.f.cfg,state,'diagnose')),64)
        from unittest.mock import patch
        with patch.object(flow,'diagnosis_paths',return_value=flow.diagnosis_paths(self.f.cfg)+['/evidence/seed/tests/test.py']):
            with self.assertRaises(ValueError):flow.preflight_plan(self.f.cfg,state,'diagnose')

    def test_tampered_rejection_is_not_forwarded_as_cto_authority(self):
        self.f.review_choice='reject_test_revision';state=self.submit()
        state['history'][0]['review']['value']['manifest_sha256']='f'*64
        self.f.con.execute('UPDATE literal_maintenance_workflows SET state=? WHERE source_task=?',
            (json.dumps(state,sort_keys=True),'rejected-author'));self.f.con.commit()
        before=len([c for c in self.f.calls if c[0]=='wake'])
        self.assertEqual(self.advance()['category'],'maintenance_evidence_rejected')
        self.assertEqual(len([c for c in self.f.calls if c[0]=='wake']),before)

    def test_database_invariant_failure_is_a_durable_owned_incident_not_a_watchdog_loop(self):
        self.advance();self.f.complete('plan');self.advance();self.advance();self.f.complete('permit');self.advance()
        calls=[]
        def conflict(*args):calls.append(True);raise sqlite3.IntegrityError('UNIQUE constraint failed: test_revision_trials.parent_issue')
        self.f.fx.prepare=conflict;state=self.advance()
        self.assertEqual(state['stage'],'blocked');self.assertEqual(state['category'],'maintenance_database_invariant_conflict')
        self.assertEqual(state['owner'],'cto');self.assertEqual(state['last_error']['type'],'IntegrityError')
        self.assertEqual(self.advance(),state);self.assertEqual(calls,[True])

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
