import unittest
from product_policy import context,review_error,VERSION

class PolicyTests(unittest.TestCase):
    def test_routine_plan_does_not_require_cto(self):
        card=context('planning');self.assertEqual(card['reviewer'],'quality_security')
        self.assertIsNone(review_error('techlead','quality_security',card))
    def test_independent_maintenance_and_architecture(self):
        for kind in ('test_maintenance','architecture','backend','frontend','quality','design','product','platform','deployment','knowledge'):
            card=context(kind);self.assertIsNone(review_error(card['author'],card['reviewer'],card))
            self.assertIsNotNone(review_error(card['author'],card['author'],card))
    def test_risk_or_assignment_cannot_be_self_declared(self):
        card=context('platform')
        self.assertIsNotNone(review_error('devops','frontend',card))
        self.assertIsNotNone(review_error('devops','cto',dict(card,risk='routine')))
        self.assertIsNotNone(review_error('backend_data','cto',card))
    def test_unknown_policy_denied(self):
        card=context('planning');card['policy_version']='unknown'
        self.assertIsNotNone(review_error('techlead','quality_security',card))
