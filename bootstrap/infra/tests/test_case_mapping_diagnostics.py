import unittest
from product_case_inventory import compare

class MappingDiagnosticsTests(unittest.TestCase):
    def test_unknown_identifiers_return_exact_executed_names(self):
        before={'tests/a.test.ts::suite before':{'path':'tests/a.test.ts'}}
        after={'tests/a.test.ts::suite after':{'path':'tests/a.test.ts'}}
        with self.assertRaises(ValueError) as result:compare(before,after,{'before':'unchanged'}, {})
        self.assertEqual(result.exception.diagnostic['before_case_ids'],list(before))
        self.assertEqual(result.exception.diagnostic['after_case_ids'],list(after))
        self.assertEqual(result.exception.diagnostic['unknown_keys'],['before'])
        self.assertEqual(result.exception.diagnostic['unknown_values'],['unchanged'])
        self.assertEqual(compare(before,after,{next(iter(before)):next(iter(after))}, {})['preserved'],1)
    def test_unchanged_cases_do_not_need_mapping(self):
        cases={'tests/a.test.ts::suite same':{'path':'tests/a.test.ts'}}
        self.assertEqual(compare(cases,cases,{}, {})['preserved'],1)
    def test_nested_rationale_is_a_schema_diagnostic_not_controller_crash(self):
        cases={'tests/a.test.ts::suite same':{'path':'tests/a.test.ts'}}
        with self.assertRaises(ValueError) as result:compare(cases,cases,{next(iter(cases)):{'status':'unchanged'}}, {})
        self.assertEqual(result.exception.diagnostic['before_case_ids'],list(cases))
        self.assertEqual(result.exception.diagnostic['unknown_values'],[{'status':'unchanged'}])
