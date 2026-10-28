"""The semantic probe cannot turn prose or unsafe decisions into approval."""
import importlib.util
import json
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('semantic_eval', Path(__file__).resolve().parents[1] / 'scripts/evaluate_review_semantics.py')
evaluation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluation)


class SemanticEvaluation(unittest.TestCase):
    def message(self, **changes):
        data = dict(next_step='inspect_existing_delivery', owner='techlead',
                    reason='Inspect existing tests before deciding on concrete defects.', delivery_approved=False)
        data.update(changes)
        return dict(tool_calls=[dict(function=dict(name='record_assessment', arguments=json.dumps(data)))])

    def test_contradictory_action_is_not_rescued_by_good_rationale(self):
        self.assertTrue(evaluation.grade(self.message(), 'inspect_existing_delivery')[0])
        self.assertFalse(evaluation.grade(self.message(next_step='request_author_changes'), 'inspect_existing_delivery')[0])

    def test_no_prose_approval_or_ceo_technical_escalation(self):
        for message in [dict(content='passed'), self.message(delivery_approved=True), self.message(owner='ceo')]:
            self.assertFalse(evaluation.grade(message, 'inspect_existing_delivery')[0])

    def test_extra_or_malformed_tool_calls_are_rejected(self):
        message = self.message()
        message['tool_calls'] *= 2
        self.assertFalse(evaluation.grade(message, 'inspect_existing_delivery')[0])
        message = self.message()
        message['tool_calls'][0]['function']['arguments'] = '{'
        self.assertFalse(evaluation.grade(message, 'inspect_existing_delivery')[0])

    def test_eval_shares_real_contract_without_case_answers(self):
        from fabriquinha.quality import CONTROL_REVIEW_CONTRACT, REVIEW_FINDINGS_CONTRACT
        self.assertIn(CONTROL_REVIEW_CONTRACT, evaluation.REVIEW_CONTEXT)
        self.assertIn(REVIEW_FINDINGS_CONTRACT, evaluation.REVIEW_CONTEXT)
        self.assertNotIn('expected-red', evaluation.REVIEW_CONTEXT)


if __name__ == '__main__':
    unittest.main()
