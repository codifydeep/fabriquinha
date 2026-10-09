import json
import unittest
from broker.suite_failure import evidence, FrozenSuiteFailure, failing_source_files, dependency_read_files, derived_numeric_diagnostic


class SuiteFailureTests(unittest.TestCase):
    def test_derived_diagnostic_preserves_historical_receipt_and_grants_no_authority(self):
        output = ('AssertionError: 2 not greater than or equal to 3\n'
                  'FAIL: test_poll (tests.New.test_poll)\nRan 386 tests\n')
        old = evidence(1, output, 'task', 'volume')
        old['numeric_assertion_details'] = []  # Actual legacy parser output.
        before = json.dumps(old, sort_keys=True)
        diagnostic = derived_numeric_diagnostic(old, output)
        self.assertEqual(json.dumps(old, sort_keys=True), before)
        self.assertEqual(diagnostic['output_sha256'], old['output_sha256'])
        self.assertEqual(diagnostic['numeric_assertion_details'], [dict(observed=2, expected=3, comparison='>=')])
        for key in ('historical_receipt_modified', 'test_defect_proven', 'test_edits_authorized', 'delivery_approval'):
            self.assertIs(diagnostic[key], False)
        with self.assertRaises(ValueError):
            derived_numeric_diagnostic(old, output + 'changed')
        for field, value in [('category', 'runner_failure_unclassified'), ('phase', 'red'), ('exit_code', 0)]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                derived_numeric_diagnostic({**old, field: value}, output)

    def test_numeric_inequalities_preserve_operator_without_private_messages(self):
        output = ('AssertionError: 2 not greater than or equal to 3\n'
                  'AssertionError: -4 not less than -5\n'
                  'AssertionError: 3 not greater than 4\n'
                  'AssertionError: 7 not less than or equal to 6\n'
                  'AssertionError: 2 not greater than or equal to 3 : private\n'
                  'AssertionError: 1000000000 not greater than 2\n'
                  'AssertionError: True not greater than 2\n'
                  'FAIL: test_poll (tests.New.test_poll)\nRan 386 tests\n')
        receipt = evidence(1, output, 'task', 'volume')
        self.assertEqual(receipt['numeric_assertion_details'], [
            dict(observed=2, expected=3, comparison='>='),
            dict(observed=-4, expected=-5, comparison='<'),
            dict(observed=3, expected=4, comparison='>'),
            dict(observed=7, expected=6, comparison='<='),
        ])
        self.assertNotIn('private', json.dumps(receipt))

    def test_numeric_inequality_witnesses_are_bounded(self):
        output = 'AssertionError: 2 not greater than or equal to 3\n' * 100
        self.assertEqual(len(evidence(1, output, 'task', 'volume')['numeric_assertion_details']), 16)

    def test_missing_attribute_preserves_identifiers_not_freeform_error_data(self):
        receipt = evidence(1, "AttributeError: module 'app.db' has no attribute 'get_item'\n"
            "AttributeError: module '../secrets' has no attribute 'token'\n"
            "AttributeError: private-user-content\nRan 3 tests\n", 'task', 'volume')
        self.assertEqual(receipt['missing_module_attributes'], [dict(module='app.db', attribute='get_item')])
        self.assertNotIn('private-user-content', json.dumps(receipt))
        self.assertNotIn('secrets', json.dumps(receipt))

    def test_dependency_inspection_is_declared_bounded_package_source_only(self):
        receipt = {'missing_module_attributes': [dict(module='app.db', attribute='get_item')]}
        declared = ['app/db.py', 'app/store.py', 'app/server.py', 'app/test_secret.py',
                    'app/private.json', 'outside/secret.py', 'app/nested/secret.py']
        self.assertEqual(dependency_read_files(receipt, declared), ['app/db.py', 'app/server.py', 'app/store.py'])
        self.assertEqual(dependency_read_files(receipt, ['app/store.py']), [])
        self.assertEqual(dependency_read_files(receipt, []), [])
        self.assertEqual(dependency_read_files(receipt, ['app/db.py'] + ['app/f%d.py' % n for n in range(17)]), [])

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
