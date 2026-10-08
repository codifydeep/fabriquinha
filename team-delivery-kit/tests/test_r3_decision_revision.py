import json
import unittest
from r3_decision_revision import qualify,record
from portable_remediation_intake import digest


class RevisionTests(unittest.TestCase):
    def setUp(self):
        self.config=dict(evidence_sha256='a'*64,evidence={'facts':{'F01':'controller_handle_missing'}},techlead='tl',cto='cto')
        self.proposal=dict(action='retain_hold',experiment='none',evidence_sha256='a'*64,reason='Gap remains',
                           fact_ids=['F01'],execution_authorized=False,release_homologated=False)
        self.review=dict(decision='request_changes',proposal_sha256=digest(self.proposal),evidence_sha256='a'*64,
                         reason='Assess recovery',fact_ids=['F01'],execution_authorized=False,release_homologated=False)
        self.state=dict(stage='awaiting_review',issue_id='issue',proposal=self.proposal,proposal_sha256=digest(self.proposal),
            diagnosis_task='author',diagnosis_wakeup='author-wake',task_id='review',wakeup_id='review-wake')
        self.author=dict(id='author',agent_id='tl',issue_id='issue',wakeup_id='author-wake',status='completed',
                         result={'output':json.dumps(self.proposal)})
        self.reviewer=dict(id='review',agent_id='cto',issue_id='issue',wakeup_id='review-wake',status='completed',
                           result={'output':json.dumps(self.review)})

    def test_real_independent_changes_preserve_both_submissions(self):
        self.assertEqual(qualify(self.config,self.state,self.review,self.author,self.reviewer),record(self.state,self.review))

    def test_forged_obsolete_self_review_and_text_only_fail(self):
        for change in (dict(agent_id='tl'),dict(wakeup_id='old'),dict(status='running'),dict(issue_id='other'),
                       dict(result={'output':'I request changes'})):
            with self.subTest(change=change),self.assertRaises((ValueError,TypeError)):
                qualify(self.config,self.state,self.review,self.author,{**self.reviewer,**change})

    def test_hold_is_only_eligible_for_explicit_policy_qualification(self):
        review={**self.review,'decision':'retain_hold'}
        task={**self.reviewer,'result':{'output':json.dumps(review)}}
        with self.assertRaises(ValueError):qualify(self.config,self.state,review,self.author,task)
        self.assertEqual(qualify(self.config,self.state,review,self.author,task,accepted_decision='retain_hold')['review'],review)
