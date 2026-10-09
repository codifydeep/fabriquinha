import unittest
from red_log_supervision import qualify


class RedLogSupervisionTests(unittest.TestCase):
    def test_only_same_validated_receipt_can_refresh_blocker(self):
        status=dict(stage='escalation_required',issue_id='issue',category='technical_decision_required:RuntimeError:validator output unavailable')
        context=dict(issue_id='issue')
        proof=dict(issue_id='issue',operation='same_red_job_log_recovery_v1',stage='complete',
            lease_status='closed',author_restarted=False,tests_reexecuted=False,delivery_approval=False,
            output_sha256='a'*64,red_output_sha256='a'*64)
        self.assertTrue(qualify(status,context,proof))
        for key,value in [('issue_id','other'),('stage','intent'),('lease_status','running'),
                          ('author_restarted',True),('tests_reexecuted',True),('delivery_approval',True),
                          ('red_output_sha256','b'*64)]:
            with self.subTest(key=key):self.assertFalse(qualify(status,context,dict(proof,**{key:value})))
        self.assertFalse(qualify(dict(status,category='other'),context,proof))
