import copy
import unittest

from broker.test_revision_review import prepare_citation_recovery


class ReviewCitationRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.path='/evidence/candidate/tests/test_new.py'
        self.state=dict(status='blocked',reason='invalid_independent_test_review:ValueError',
            source_task='source',candidate_volume='frozen',manifest_sha256='a'*64,
            wakeup_id='wake',terminal_contract='typed-review-v1',evidence_policy=1,
            read_evidence={self.path:dict(lines=51,total_lines=51,next_offset=None)},
            review_failure=dict(task_id='review',detail='finding quote not observed at exact line'))
        self.red=dict(task_id='source',volume='frozen',red=dict(manifest_sha256='a'*64,
            test_sha256={'tests/test_new.py':'b'*64}))
        self.task=dict(id='review',status='completed',agent_id='reviewer',wakeup_id='wake')
        self.decision=dict(action='reject_test_revision',manifest_sha256='a'*64,optional_files=[],
                           findings=[{'quote':'invalid source quote'}],reason='Missing behavioral coverage')

    def test_one_new_review_preserves_invalid_decision_and_frozen_source(self):
        before=copy.deepcopy(self.state)
        new=prepare_citation_recovery(self.state,self.red,self.task,'reviewer',self.decision,[self.path])
        self.assertEqual(self.state,before)
        self.assertEqual(new['status'],'dispatch_intent')
        self.assertNotIn('wakeup_id',new)
        self.assertEqual(new['citation_recovery']['prior_state'],before)
        self.assertEqual(new['citation_recovery']['invalid_decision'],self.decision)
        self.assertFalse(new['citation_recovery']['approval'])
        self.assertFalse(new['citation_recovery']['author_restarted'])
        self.assertEqual(new['candidate_volume'],'frozen')
        self.assertEqual(prepare_citation_recovery(new,self.red,self.task,'reviewer',self.decision,[self.path]),new)

    def test_verdict_read_identity_and_other_failures_cannot_be_overridden(self):
        for field,value in [('detail','snapshot mismatch'),('task_id','different')]:
            state=copy.deepcopy(self.state);state['review_failure'][field]=value
            with self.assertRaises(ValueError): prepare_citation_recovery(state,self.red,self.task,'reviewer',self.decision,[self.path])
        for key,value in [('status','running'),('agent_id','author'),('wakeup_id','wrong')]:
            with self.assertRaises(ValueError): prepare_citation_recovery(self.state,self.red,{**self.task,key:value},'reviewer',self.decision,[self.path])
        for key,value in [('action','approve_test_revision'),('manifest_sha256','c'*64),('optional_files',['new.py'])]:
            with self.assertRaises(ValueError): prepare_citation_recovery(self.state,self.red,self.task,'reviewer',{**self.decision,key:value},[self.path])
        self.state['read_evidence'][self.path]['lines']=50
        with self.assertRaises(ValueError): prepare_citation_recovery(self.state,self.red,self.task,'reviewer',self.decision,[self.path])
