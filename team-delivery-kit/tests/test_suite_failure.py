import json
import unittest
from broker.suite_failure import evidence, FrozenSuiteFailure, failing_source_files


class SuiteFailureTests(unittest.TestCase):
    def test_failed_baseline_files_are_bound_to_known_manifest_for_diagnosis(self):
        receipt = {'failures': [{'qualified_name': 'tests.test_old.Cases.test_keep'},
                                {'qualified_name': 'tests.test_new.Cases.test_change'},
                                {'qualified_name': 'outside.secret.test_steal'}]}
        self.assertEqual(failing_source_files(receipt, ['tests/test_old.py', 'tests/test_new.py']),
                         ['tests/test_new.py', 'tests/test_old.py'])
        self.assertEqual(failing_source_files(receipt, ['tests/test_wrong.py']), [])

    def test_numeric_evidence_preserves_type_and_impossible_count_witness(self):
        output = ("AssertionError: 1 != '1'\n"
                  "AssertionError: {'total': 2, 'open': 1, 'completed': 1} != "
                  "{'total': '2', 'open': '2', 'completed': '1'}\n"
                  "KeyError: 'filename'\nAssertionError: 'private' != 'another private'\n"
                  'FAIL: test_new (tests.New.test_new)\nRan 114 tests\n')
        receipt = evidence(1, output, 'task', 'volume')
        details = receipt['numeric_assertion_details']
        self.assertEqual(details[0], {'observed': 1, 'expected': '1'})
        self.assertEqual(details[1]['observed']['open'], 1)
        self.assertEqual(details[1]['expected']['open'], '2')
        self.assertEqual(receipt['missing_metadata_keys'], ['filename'])
        self.assertNotIn('private', json.dumps(receipt))

    def test_executed_failure_is_not_infrastructure_or_successful_author(self):
        output = ('FAIL: test_poll (tests.test_browser.New.test_poll)\n'
                  'AssertionError: private-user-content\n'
                  'ERROR: test_source (tests.test_browser.New.test_source)\n'
                  "KeyError: 'filename'\nRan 114 tests in 1s\nFAILED (failures=1, errors=1)\n")
        receipt = evidence(1, output, 'task', 'volume')
        self.assertEqual(receipt['category'], 'executed_test_failure')
        self.assertEqual(receipt['tests_executed'], 114)
        self.assertEqual(receipt['exception_types'], ['AssertionError', 'KeyError'])
        self.assertEqual(len(receipt['failures']), 2)
        self.assertNotIn('private-user-content', json.dumps(receipt))
        self.assertIs(FrozenSuiteFailure(receipt).validation_failure, receipt)

    def test_missing_runner_is_unclassified_not_assertion_failure(self):
        receipt = evidence(127, 'python3: not found\n', 'task', 'volume')
        self.assertEqual(receipt['category'], 'runner_failure_unclassified')
        self.assertIsNone(receipt['tests_executed'])
        self.assertEqual(receipt['failures'], [])

    def test_success_is_not_accepted_as_failure(self):
        with self.assertRaises(ValueError):
            evidence(0, 'Ran 114 tests\nOK', 'task', 'volume')
