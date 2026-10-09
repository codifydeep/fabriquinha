import copy
import unittest
from broker.failed_candidate_plan import prepare,review,instruction,paths


class FailedCandidatePlanTests(unittest.TestCase):
    def setUp(self):
        self.route=dict(issue_id='issue',author='author',cto='cto',techlead='lead',
                        contract_sha256='hash',test_first_files=['tests/test_new.py'])
        failure=dict(diagnostic_read_files=['app.js'],source_task='source')
        self.data=dict(source_task='source',source_status='failed',target='cto',wakeup_id='wake',
            author_edit_files=['app.js'],validation_failure=failure,
            failed_execution_diagnostic=dict(status='diagnostic_only_not_approved',failure=failure))
        self.task=dict(id='cto-task',issue_id='issue',agent_id='cto',status='completed',wakeup_id='wake')
        self.decision=dict(action='request_correction',reason='Wire the existing loader into startup and polling.',optional_files=[])
        self.reads=paths(self.route,self.data)
    def test_cto_proposal_and_peer_review_are_not_execution_or_delivery_approval(self):
        plan=prepare(self.route,self.data,self.task,self.decision,self.reads)
        data=dict(self.data,failed_candidate_plan=plan,target='lead',wakeup_id='review-wake')
        self.assertLess(len(instruction(self.route,data)),3800)
        peer=dict(id='lead-task',agent_id='lead',issue_id='issue',status='completed',wakeup_id='review-wake')
        result=review(self.route,data,peer,self.decision,self.reads)
        for key in ('author_execution_authorized','tests_may_change','delivery_approval','retry_budget_reset'):
            self.assertFalse(result[key])
    def test_missing_reads_wrong_roles_and_authority_expansion_are_rejected(self):
        with self.assertRaises(ValueError):prepare(self.route,self.data,self.task,self.decision,[])
        for key,value in [('agent_id','author'),('status','failed'),('wakeup_id','old'),('issue_id','other')]:
            with self.assertRaises(ValueError):prepare(self.route,self.data,dict(self.task,**{key:value}),self.decision,self.reads)
        with self.assertRaises(ValueError):prepare(self.route,self.data,self.task,dict(self.decision,optional_files=['test.py']),self.reads)
    def test_stale_snapshot_and_self_review_cannot_qualify(self):
        plan=prepare(self.route,self.data,self.task,self.decision,self.reads)
        data=dict(self.data,failed_candidate_plan=plan,target='lead',wakeup_id='review-wake')
        peer=dict(id='cto-task',agent_id='lead',issue_id='issue',status='completed',wakeup_id='review-wake')
        with self.assertRaises(ValueError):review(self.route,data,peer,self.decision,self.reads)
        data=copy.deepcopy(data);data['failed_execution_diagnostic']['volume']='other'
        with self.assertRaises(ValueError):instruction(self.route,data)
