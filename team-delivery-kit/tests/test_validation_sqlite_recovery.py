import copy
import unittest
from broker import validation_sqlite_recovery as recovery


class SqliteValidationRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.data=dict(source_task='author',source_status='completed',error='database is locked',
            error_type='OperationalError',dispatch_stage='diagnose',attempts=2,
            bounded_replan_origin={'grant_sha256':'g'},target='lead',wakeup_id='w',
            instruction='Old diagnostic hypothesis',recipient_task='lead-task')

    def test_preserves_attempts_and_all_old_evidence_without_author_restart(self):
        before=copy.deepcopy(self.data)
        result=recovery.prepare(self.data,'author')
        self.assertEqual(self.data,before)
        self.assertEqual(result['attempts'],2)
        self.assertEqual(result['sqlite_validation_recovery']['previous_handoff'],before)
        self.assertFalse(result['sqlite_validation_recovery']['author_restarted'])
        self.assertFalse(result['sqlite_validation_recovery']['tests_may_change'])
        self.assertFalse(result['sqlite_validation_recovery']['retry_budget_reset'])
        self.assertFalse(result['sqlite_validation_recovery']['delivery_approval'])
        self.assertNotIn('wakeup_id',result)
        self.assertEqual(recovery.prepare(result,'author'),result)
        with self.assertRaises(ValueError):recovery.prepare(result,'other')

    def test_rejects_product_failure_existing_evidence_or_wrong_source(self):
        for change in ({'source_status':'failed'},{'error':'assertion failed'},
                       {'validation_failure':{'category':'executed_test_failure'}},
                       {'evidence':{'manifest_sha256':'hash'}},{'dispatch_stage':'ready_review'},
                       {'source_task':'other'}):
            with self.subTest(change=change),self.assertRaises(ValueError):
                recovery.prepare({**self.data,**change},'author')


if __name__=='__main__':unittest.main()
