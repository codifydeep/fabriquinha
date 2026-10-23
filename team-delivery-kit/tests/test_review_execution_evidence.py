"""Synthetic evidence shape tests; no actual Hermes/native qualification."""
import copy
import unittest
from review_execution_evidence import validate


def evidence():
    return dict(operation='real_hermes_review_execution_controls_v1',
        stall=dict(provider_calls=3,category='read_progress_stalled',fixture_iterations=40),
        budget=dict(provider_calls=1,category='iteration_budget_exhausted',fixture_iterations=1),
        preflight_then_dispatch=True,direct_duplicate_denied=True,snapshot_unchanged=True,model_calls=0)


class ReviewExecutionEvidenceTests(unittest.TestCase):
    def test_exact_controls_only(self):
        self.assertEqual(validate(evidence()),evidence())
        for change in (dict(model_calls=False),dict(model_calls=1),dict(snapshot_unchanged=1),
                dict(preflight_then_dispatch=False),dict(direct_duplicate_denied=False),dict(approval=True)):
            with self.subTest(change=change),self.assertRaises(ValueError):validate({**evidence(),**change})

    def test_no_missing_case_bool_counter_or_changed_stop_category(self):
        for mode in ('stall','budget'):
            value=evidence();del value[mode]
            with self.assertRaises(ValueError):validate(value)
            for field,bad in [('provider_calls',True),('fixture_iterations',True),('category','success')]:
                value=copy.deepcopy(evidence());value[mode][field]=bad
                with self.assertRaises(ValueError):validate(value)
