import copy
import unittest
from broker import review_reconsideration as reconsideration


class ReconsiderationTests(unittest.TestCase):
    def fixture(self):
        route=dict(issue_id='issue',author='author',techlead='reviewer',cto='cto',test_first_files=['tests/test_new.py'])
        red=dict(issue_id='issue',task_id='author-task',volume='candidate',red={'manifest_sha256':'a'*64})
        state=dict(status='blocked',evidence_policy=1,terminal_contract='typed-review-v1',
            source_task='author-task',candidate_volume='candidate',previous_volume='previous',
            manifest_sha256='a'*64,review_task='review-task',wakeup_id='review-wake',
            decision=dict(action='reject_test_revision',reason='Claim',manifest_sha256='a'*64),
            reason='Claim',rejection_diagnosis=dict(target='cto',wakeup_id='cto-wake',status='awaiting_cto'))
        task=dict(id='cto-task',issue_id='issue',agent_id='cto',wakeup_id='cto-wake',status='completed')
        reads={f'/evidence/{tree}/tests/test_new.py':dict(lines=2,total_lines=2) for tree in ('candidate','previous')}
        finding=dict(kind='review_disagreement',tree='candidate',path='tests/test_new.py',
            test='__module__',line=1,quote='assert value',expected='Existing check preserved',observed='Same check present')
        decision=dict(action='request_review_reconsideration',reason='Reassess this exact snapshot',optional_files=[],findings=[finding])
        report=dict(candidate={'files':{'tests/test_new.py':dict(lines=['assert value',''],methods={})}},
            previous={'files':{'tests/test_new.py':dict(lines=['assert value',''],methods={})}},
            summary={'candidate_manifest':'a'*64,'files':{'tests/test_new.py':{}}})
        return state,red,route,task,decision,reads,report

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

    def test_forged_objection_self_review_partial_read_or_second_request_is_rejected(self):
        for mutation in ('author','running','snapshot','wakeup','quote','partial','approval','empty'):
            args=list(copy.deepcopy(self.fixture()))
            if mutation=='author':args[3]['agent_id']='author'
            if mutation=='running':args[3]['status']='running'
            if mutation=='snapshot':args[1]['red']['manifest_sha256']='b'*64
            if mutation=='wakeup':args[3]['wakeup_id']='other'
            if mutation=='quote':args[4]['findings'][0]['quote']='not present'
            if mutation=='partial':args[5]['/evidence/previous/tests/test_new.py']['lines']=1
            if mutation=='approval':args[4]['action']='approve_test_revision'
            if mutation=='empty':args[4]['findings']=[]
            with self.assertRaises(ValueError,msg=mutation):reconsideration.prepare(*args)
        args=list(self.fixture());result=reconsideration.prepare(*args)
        args[0]=result;args[3]['id']='another-cto-task'
        with self.assertRaises(ValueError):reconsideration.prepare(*args)
