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
            'test_path':'tests/test.py','literal':'NODE_HARNESS','counterexample':{'receipt':'bound'}}
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
                if phase=='plan':value={'action':'request_test_revision','reason':'Preserve assertions; repair driver','optional_files':[]}
                elif phase=='review':value={'action':parent.review_choice,'reason':'Measured selective driver, unchanged assertions','optional_files':[], 'manifest_sha256':s['inspection']['candidate_manifest_sha256']}
                else:value={**flow.review_context(c,s,phase),'action':parent.choice,'reason':'Evidence justifies scoped author proposal',
                    'author_retry_authorized':False,'execution_authorized':False,'delivery_approval':False}
                return {'task_id':t['id'],'agent_id':t['agent_id'],'wakeup_id':t['wakeup_id'],'value':value}
            def prepare(_,c,s):parent.calls.append(('prepare',));return {'issue_base':'qualified','seed':'frozen'}
            def snapshot(_,c,s,t):return {'volume':'new-frozen','task_id':t['id']}
            def inspect(_,c,s):return {'candidate_manifest_sha256':'a'*64,'stale_witness_selectivity_passed':True,
                'non_target_files_unchanged':True,'structure':{'outside_literal_bytes_preserved':True}}
            def validate_inspection(_,c,s,r):parent.assertTrue(r['non_target_files_unchanged'])
            def reseed(_,c,s):parent.calls.append(('reseed',s['history'][-1]['author_task']));return {'seed':'exact-rejected-artifact'}
        self.fx=Effects()

    def advance(self,now=1):return flow.advance(self.con,'source',self.fx,now=now)
    def complete(self,phase,revision=0):
        actor={'triage':'lead','plan':'cto','permit':'lead','author':'author','review':'lead'}[phase]
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

    def test_broken_sensitivity_never_reaches_review_or_source_adoption(self):
        self.reach_author();self.advance();self.complete('author');self.advance()
        real=self.fx.inspect;self.fx.inspect=lambda *a:{**real(*a),'stale_witness_selectivity_passed':False}
        self.advance();s=self.advance();self.assertEqual(s['category'],'maintenance_sensitivity_failed')

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
        self.assertFalse(s['source_reset']);before=list(self.calls);self.advance();self.assertEqual(before,self.calls)

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
