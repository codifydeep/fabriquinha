import copy
import unittest
from broker.review_precondition_recovery import prepare,ERROR


class ReviewPreconditionRecoveryTests(unittest.TestCase):
    def fixture(self):
        route=dict(issue_id='issue',author='author',reviewer='reviewer')
        task=dict(id='failed-review',issue_id='issue',agent_id='reviewer',status='completed')
        data=dict(source_task='source',dispatch_stage='ready_review',target='reviewer',
            recipient_task='failed-review',control_error=ERROR,review_retries=1,
            snapshot=dict(volume='frozen'),evidence=dict(manifest_sha256='a'*64),
            wakeup_id='old-wake',instruction='old incomplete instructions')
        proof=dict(operation='omitted_independent_review_preconditions',review_task='failed-review',
            source_task='source',volume='frozen',manifest_sha256='a'*64,
            closed_review_lease=True,suite_status='issued',read_paths=['/delivery/app.js'],
            delivery_approval=False)
        return data,route,task,proof

    def test_fresh_review_preserves_failed_evidence_and_retry_count(self):
        data,route,task,proof=self.fixture();old=copy.deepcopy(data)
        result=prepare(data,route,task,proof)
        self.assertEqual(data,old)
        self.assertEqual(result['review_retries'],1)
        self.assertEqual(result['snapshot'],data['snapshot'])
        self.assertEqual(result['evidence'],data['evidence'])
        self.assertEqual(result['review_preconditions_recovery']['previous_blocker'],old)
        self.assertFalse(result['review_preconditions_recovery']['delivery_approval'])
        self.assertFalse(result['review_preconditions_recovery']['author_restarted'])
        self.assertNotIn('recipient_task',result);self.assertNotIn('wakeup_id',result)
        self.assertTrue(result['policy_revalidation'])
        self.assertEqual(result['inspection_revalidation']['read_paths'],proof['read_paths'])

    def test_changed_snapshot_active_lease_or_completed_suite_cannot_recover(self):
        data,route,task,proof=self.fixture()
        for field,value in [('source_task','other'),('manifest_sha256','b'*64),
                            ('volume','other'),('closed_review_lease',False),
                            ('suite_status','passed'),('delivery_approval',True),('read_paths',[])]:
            with self.subTest(field=field),self.assertRaises(ValueError):
                prepare(data,route,task,{**proof,field:value})
        with self.assertRaises(ValueError):prepare(data,route,{**task,'status':'running'},proof)
        with self.assertRaises(ValueError):prepare(data,{**route,'reviewer':'author'},task,proof)

    def test_consumed_recovery_or_other_failure_cannot_repeat(self):
        data,route,task,proof=self.fixture()
        changed=prepare(data,route,task,proof)
        with self.assertRaises(ValueError):prepare({**data,**changed},route,task,proof)
        with self.assertRaises(ValueError):prepare({**data,'control_error':'functional failure'},route,task,proof)
