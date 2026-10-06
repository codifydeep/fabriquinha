import copy
import unittest

from planning_intake import source_clarification


class ProductSourceClarificationTests(unittest.TestCase):
    def setUp(self):
        self.proposal = {'role': 'product', 'stories': [{'title': 'Service indicator',
                          'acceptance': ['Availability is visible']}],
                         'business_questions': ['Is the indicator informational?']}
        self.ledger = {'stage': 'blocked_awaiting_ceo', 'issues': {'product': 'source-issue'},
                       'outputs': {'product': {'proposal': self.proposal, 'task_id': 'source-task'}},
                       'questions': self.proposal['business_questions'], 'owner': 'ceo',
                       'brief_sha256': 'a' * 64, 'configuration_sha256': 'b' * 64}

    def test_one_fresh_proposal_preserves_original_question_and_input_identity(self):
        original = copy.deepcopy(self.ledger)
        result = source_clarification(self.ledger)
        self.assertEqual(self.ledger, original)
        self.assertEqual(result['brief_sha256'], original['brief_sha256'])
        self.assertEqual(result['outputs'], {})
        self.assertEqual(result['prior_product_clarification']['questions'], original['questions'])
        self.assertIs(result['prior_product_clarification']['ceo_answer_created'], False)
        self.assertIs(result['prior_product_clarification']['scope_approval_created'], False)
        result.update(stage='blocked_awaiting_ceo', outputs=original['outputs'], questions=original['questions'])
        self.assertIsNone(source_clarification(result))

    def test_technical_failure_is_not_retried_as_business_clarification(self):
        self.ledger['stage'] = 'blocked'
        self.assertIsNone(source_clarification(self.ledger))

    def test_question_or_role_drift_is_rejected(self):
        self.ledger['questions'] = ['Other question']
        with self.assertRaisesRegex(ValueError, 'identity'):
            source_clarification(self.ledger)
