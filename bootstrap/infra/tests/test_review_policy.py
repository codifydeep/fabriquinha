import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from review_policy import REVIEWERS, validate_review

class ReviewPolicyTests(unittest.TestCase):
    def test_matrix(self):
        for author, reviewer in REVIEWERS.items():
            self.assertIsNone(validate_review(author, reviewer))
            self.assertIsNotNone(validate_review(author, author))

    def test_cto_cannot_approve_cto_plan(self):
        self.assertIsNotNone(validate_review('cto', 'cto'))
        self.assertIsNone(validate_review('cto', 'techlead'))

    def test_wrong_independent_reviewer_rejected(self):
        self.assertIsNotNone(validate_review('devops', 'produto'))
        self.assertIsNotNone(validate_review('qa', 'techlead'))
