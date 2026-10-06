import unittest
from unittest.mock import patch
import recover_u3_qa_cleanup as recovery


class CleanupRecoveryTests(unittest.TestCase):
    def state(self):return dict(stage='blocked',request={'source_sha':recovery.qa.SHA},
        reason='post-deploy browser QA  cleanup: browser QA cleanup timeout; absence unproven')
    def test_recovery_only_accepts_exact_cleanup_incident_and_full_checks(self):
        checks=list(range(40));proof={'result':{'contexts':2,'checks':checks}}
        with patch.object(recovery.deploy,'cleanup_evidence',return_value=['verified']) as verify:
            self.assertEqual(recovery.validate(self.state(),proof,{'browser_checks':checks},'path'),['verified'])
            verify.assert_called_once()
        for state in (dict(self.state(),stage='validation_passed'),dict(self.state(),reason='functional test failed')):
            with self.assertRaises(ValueError):recovery.validate(state,proof,{'browser_checks':checks},'path')
    def test_partial_or_wrong_context_evidence_cannot_recover(self):
        for result in ({'contexts':1,'checks':list(range(40))},{'contexts':2,'checks':list(range(39))}):
            with self.assertRaises(ValueError):recovery.validate(self.state(),{'result':result},
                {'browser_checks':list(range(40))},'path')
