import unittest
from product_review_feedback import same_findings

class NoveltyTests(unittest.TestCase):
    def test_receipt_hash_is_not_new_evidence(self):
        self.assertTrue(same_findings('team-decision:aaa\nMissing mapping for the renamed case.','team-decision:bbb\nMissing mapping for the renamed case.'))
    def test_new_executed_failure_is_not_same_rejection_loop(self):
        self.assertFalse(same_findings('Missing case mapping for the renamed error register test.','The existing cases passed; validation now found a separate empty file with no suite. Correct the new artifact.'))
