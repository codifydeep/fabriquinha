import copy
import unittest
from broker.test_revision_review import prepare_observed_reconciliation


class ObservedReviewReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.state=dict(status='blocked',manifest_sha256='hash',source_task='author',wakeup_id='wake',
            reason='invalid_independent_test_review:ValueError',review_failure=dict(task_id='review',detail='review requires observed artifact reads'))
        self.red=dict(task_id='author',red=dict(manifest_sha256='hash',test_sha256={'tests/new.py':'sha'}))
        self.task=dict(id='review',status='completed',wakeup_id='wake')
        self.reads={'/evidence/candidate/tests/new.py':dict(lines=432,total_lines=432)}

    def apply(self):return prepare_observed_reconciliation(self.state,self.red,self.task,self.reads)

    def test_reconciles_same_verdict_without_approval_or_new_execution_and_preserves_failure(self):
        result=self.apply();self.assertEqual(result['status'],'awaiting_review')
        self.assertFalse(result['observed_reconciliation']['delivery_approval'])
        self.assertEqual(result['observed_reconciliation']['prior_failure'],self.state['review_failure'])
        self.assertNotIn('decision',result);self.assertEqual(self.state['status'],'blocked')
        self.assertEqual(prepare_observed_reconciliation(result,self.red,self.task,self.reads),result)

    def test_incomplete_reads_wrong_task_or_snapshot_cannot_resume(self):
        self.reads['/evidence/candidate/tests/new.py']['lines']=431
        with self.assertRaises(ValueError):self.apply()
        self.reads['/evidence/candidate/tests/new.py']['lines']=432
        self.task['wakeup_id']='wrong'
        with self.assertRaises(ValueError):self.apply()
        self.task['wakeup_id']='wake';self.red['red']['manifest_sha256']='different'
        with self.assertRaises(ValueError):self.apply()

    def test_explicit_rejection_other_failure_and_unfinished_task_cannot_be_erased(self):
        original=copy.deepcopy(self.state)
        self.state['decision']={'action':'reject_test_revision'}
        with self.assertRaises(ValueError):self.apply()
        self.state=original;self.state['review_failure']['detail']='different failure'
        with self.assertRaises(ValueError):self.apply()
        self.state['review_failure']['detail']='review requires observed artifact reads';self.task['status']='running'
        with self.assertRaises(ValueError):self.apply()
