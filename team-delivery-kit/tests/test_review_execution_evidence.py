"""Synthetic evidence shape tests; no actual Hermes/native qualification."""
import copy
import unittest
import review_execution_evidence as contract
from review_execution_evidence import validate


def evidence():
    return dict(operation='real_hermes_review_execution_controls_v1',
        stall=dict(provider_calls=3,category='read_progress_stalled',fixture_iterations=40),
        budget=dict(provider_calls=1,category='iteration_budget_exhausted',fixture_iterations=1),
        preflight_then_dispatch=True,direct_duplicate_denied=True,snapshot_unchanged=True,model_calls=0)


def scale_evidence():
    return dict(operation='real_hermes_review_scale_compaction_v1',files=71,pages=219,
        main_provider_calls=6,summary_provider_calls=1,max_iterations=40,complete_files=71,
        compactions=1,dropped_read_pairs=16,duplicate_reads=0,eof_reads=0,
        out_of_recommended_reads=1,mixed_offset_batches=1,
        largest_batch_chars=300000,legacy_turn_budget_chars=200000,
        review_turn_budget_chars=8*1024*1024,spill_previews=0,legacy_spill_observed=True,
        tool_only_from_first_call=True,snapshot_unchanged=True,model_calls=0,tests_approved=False,delivery_approval=False)


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

    def test_scale_fixture_is_fixed_and_requires_real_measured_compaction(self):
        files=contract.scale_files()
        self.assertEqual(len(files),71);self.assertEqual(len(files['scale/file-000.py'].splitlines()),868)
        self.assertEqual(len(files['scale/file-001.py'].splitlines()),205)
        self.assertTrue(all(p.startswith('scale/file-') and isinstance(v,bytes) for p,v in files.items()))
        self.assertEqual(sum(map(len,files.values())),563066)
        self.assertEqual(contract.validate_scale(scale_evidence()),scale_evidence())
        twice={**scale_evidence(),'compactions':2,'summary_provider_calls':2}
        self.assertEqual(contract.validate_scale(twice),twice)
        for change in (dict(compactions=0),dict(dropped_read_pairs=0),dict(dropped_read_pairs=True),
                dict(summary_provider_calls=0),dict(complete_files=70),dict(main_provider_calls=24),
                dict(compactions=5,summary_provider_calls=5),dict(summary_provider_calls=2),
                dict(tool_only_from_first_call=False),dict(tool_only_from_first_call=1),dict(main_provider_calls=23),
                dict(out_of_recommended_reads=0),dict(out_of_recommended_reads=True),
                dict(mixed_offset_batches=0),dict(mixed_offset_batches=True),
                dict(largest_batch_chars=200000),dict(largest_batch_chars=True),
                dict(review_turn_budget_chars=16*1024*1024),dict(spill_previews=1),dict(legacy_spill_observed=False),
                dict(duplicate_reads=1),dict(eof_reads=1),dict(tests_approved=True),dict(model_calls=False)):
            with self.subTest(change=change),self.assertRaises(ValueError):contract.validate_scale({**scale_evidence(),**change})
