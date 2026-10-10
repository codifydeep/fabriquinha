import copy
import unittest
import time
from types import SimpleNamespace
from unittest.mock import patch
from broker import review_reconsideration as reconsideration


class ReconsiderationTests(unittest.TestCase):
    def test_mediation_prompt_fits_gateway_and_preserves_full_claim(self):
        from broker.test_revision_review import mediation_instruction
        state={'reason':'x'*1200,'comparison':{'files':{}}}
        paths=['/evidence/'+tree+'/tests/test_feedback_latest_ui.py' for tree in ('candidate','previous')]
        note=mediation_instruction(state,paths)
        self.assertLessEqual(len('DELIVERY_HANDOFF '+'a'*64+'\n'+note),4000)
        self.assertIn(state['reason'],note)
        self.assertIn('request_review_reconsideration',note)
        self.assertIn('DELIVERY_REVIEW_RECONSIDERATION_V1',note)
        for p in paths:self.assertIn(p,note)

    def test_contract_upgrade_preserves_old_cto_decision_and_recovery_budget(self):
        state,red,route,task,decision,reads,report=self.fixture()
        state['rejection_diagnosis'].update(status='revision_required',decision_task=task['id'],
            decision={'action':'request_test_revision','reason':'Keep check','optional_files':[]},
            schema_recovery={'attempt_limit':1,'failed_task':'failed-original'})
        before=copy.deepcopy(state)
        upgraded=reconsideration.upgrade_state(state,red,task)
        self.assertEqual(upgraded['review_mediation_upgrade']['prior_state'],before)
        self.assertEqual(upgraded['rejection_diagnosis']['status'],'dispatch_intent')
        self.assertEqual(upgraded['rejection_diagnosis']['schema_recovery'],before['rejection_diagnosis']['schema_recovery'])
        self.assertNotIn('technical_replan_certificate',upgraded)
        self.assertFalse(upgraded['review_mediation_upgrade']['delivery_approval'])
        self.assertFalse(upgraded['review_mediation_upgrade']['limits_increased'])
        self.assertEqual(reconsideration.upgrade_state(upgraded,red,task),upgraded)
    def fixture(self):
        route=dict(issue_id='issue',author='author',techlead='reviewer',cto='cto',test_first_files=['tests/test_new.py'])
        red=dict(issue_id='issue',task_id='author-task',volume='candidate',red={'manifest_sha256':'a'*64})
        state=dict(status='blocked',evidence_policy=1,terminal_contract='typed-review-v1',
            source_task='author-task',candidate_volume='candidate',previous_volume='previous',
            manifest_sha256='a'*64,review_task='review-task',wakeup_id='review-wake',
            decision=dict(action='reject_test_revision',reason='Claim',manifest_sha256='a'*64),
            reason='Claim',rejection_diagnosis=dict(target='cto',wakeup_id='cto-wake',status='awaiting_cto',
                mediation_contract='immutable-review-reconsideration-v1'))
        task=dict(id='cto-task',issue_id='issue',agent_id='cto',wakeup_id='cto-wake',status='completed')
        reads={f'/evidence/{tree}/tests/test_new.py':dict(lines=2,total_lines=2) for tree in ('candidate','previous')}
        finding=dict(kind='review_disagreement',tree='candidate',path='tests/test_new.py',
            test='__module__',line=1,quote='assert value',expected='Existing check preserved',observed='Same check present')
        decision=dict(action='request_review_reconsideration',reason='Reassess this exact snapshot',optional_files=[],findings=[finding])
        report=dict(candidate={'files':{'tests/test_new.py':dict(lines=['assert value',''],methods={})}},
            previous={'files':{'tests/test_new.py':dict(lines=['assert value',''],methods={})}},
            summary={'candidate_manifest':'a'*64,'files':{'tests/test_new.py':{}}})
        state['comparison']=copy.deepcopy(report['summary'])
        state['rejection_diagnosis']['dispatched_at']=time.time()
        return state,red,route,task,decision,reads,report

    def test_real_rejection_handler_requests_new_review_not_new_author(self):
        from broker import test_revision_review as revision
        state,red,route,task,decision,reads,report=self.fixture()
        config={'reviewer':'reviewer'}
        effects=SimpleNamespace(read_evidence=lambda _:reads,decision=lambda _:decision)
        with patch.object(revision,'validate_evidence') as validated, \
                patch.object(revision,'_save') as saved, \
                patch.object(revision,'_save_rejection') as rejected, \
                patch('broker.test_review_report.load',return_value=report):
            revision.reconcile_rejection(SimpleNamespace(),route,[task],effects,red,config,state)
        self.assertTrue(validated.called)
        saved.assert_called_once();rejected.assert_not_called()
        updated=saved.call_args.args[2]
        self.assertEqual(updated['status'],'dispatch_intent')
        self.assertNotIn('technical_replan_certificate',updated)
        self.assertFalse(updated['review_reconsideration']['test_changes_authorized'])

    def test_reconsideration_preserves_history_and_only_requests_new_review(self):
        args=self.fixture();before=copy.deepcopy(args[0]);result=reconsideration.prepare(*args)
        self.assertEqual(args[0],before)
        self.assertEqual(result['status'],'dispatch_intent')
        self.assertEqual(result['manifest_sha256'],'a'*64)
        self.assertEqual(result['candidate_volume'],'candidate')
        self.assertNotIn('decision',result);self.assertNotIn('review_task',result)
        self.assertNotIn('technical_replan_certificate',result)
        proof=result['review_reconsideration']
        self.assertEqual(proof['prior_state'],before)
        self.assertEqual(proof['attempt_limit'],1)
        self.assertFalse(proof['delivery_approval']);self.assertFalse(proof['author_restarted'])
        self.assertEqual(reconsideration.prepare(result,*args[1:]),result)

    def test_first_submission_can_be_reconsidered_without_fabricated_history(self):
        args=list(self.fixture());args[0].pop('previous_volume');args[6]['previous']=None
        args[5].pop('/evidence/previous/tests/test_new.py')
        result=reconsideration.prepare(*args,initial=True)
        self.assertEqual(result['status'],'dispatch_intent')
        self.assertNotIn('previous_volume',result)
        self.assertFalse(result['review_reconsideration']['delivery_approval'])

    def test_forged_objection_self_review_partial_read_or_second_request_is_rejected(self):
        for mutation in ('author','running','snapshot','wakeup','quote','partial','approval','empty','comparison'):
            args=list(copy.deepcopy(self.fixture()))
            if mutation=='author':args[3]['agent_id']='author'
            if mutation=='running':args[3]['status']='running'
            if mutation=='snapshot':args[1]['red']['manifest_sha256']='b'*64
            if mutation=='wakeup':args[3]['wakeup_id']='other'
            if mutation=='quote':args[4]['findings'][0]['quote']='not present'
            if mutation=='partial':args[5]['/evidence/previous/tests/test_new.py']['lines']=1
            if mutation=='approval':args[4]['action']='approve_test_revision'
            if mutation=='empty':args[4]['findings']=[]
            if mutation=='comparison':args[6]['summary']['candidate_manifest']='b'*64
            with self.assertRaises(ValueError,msg=mutation):reconsideration.prepare(*args)
        args=list(self.fixture());result=reconsideration.prepare(*args)
        args[0]=result;args[3]['id']='another-cto-task'
        with self.assertRaises(ValueError):reconsideration.prepare(*args)
