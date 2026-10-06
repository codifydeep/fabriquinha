import hashlib
import unittest

from broker.framework_mark_diagnosis import diagnose


SOURCE = b'''import shutil
import pytest
def available():
    return shutil.which("node") is not None
pytestmark = pytest.mark.skipif(not available(), reason="node prerequisite")
def test_behavior():
    assert False
'''


class FrameworkMarkDiagnosisTests(unittest.TestCase):
    def check(self, data=SOURCE):
        return diagnose(data, hashlib.sha256(data).hexdigest())

    def test_exact_node_predicate_is_classified_without_execution(self):
        result = self.check()
        self.assertEqual(result['predicate'], 'skip_when_node_absent')
        self.assertFalse(result['executed_source'])
        self.assertFalse(result['delivery_approval'])

    def test_stale_hash_rejected(self):
        with self.assertRaises(ValueError):
            diagnose(SOURCE, '0' * 64)

    def test_helper_side_effects_and_other_dependencies_rejected(self):
        for data in (SOURCE.replace(b'return shutil', b'print("side effect")\n    return shutil'),
                     SOURCE.replace(b'"node"', b'"docker"'),
                     SOURCE.replace(b'is not None', b'is None'),
                     SOURCE.replace(b'not available()', b'available()')):
            with self.subTest(digest=hashlib.sha256(data).hexdigest()), self.assertRaises(ValueError):
                self.check(data)

    def test_shadowed_module_or_helper_rejected(self):
        for data in (SOURCE + b'\nshutil = fake\n', SOURCE + b'\navailable = fake\n',
                     SOURCE.replace(b'import shutil', b'import fake as shutil')):
            with self.subTest(digest=hashlib.sha256(data).hexdigest()), self.assertRaises(ValueError):
                self.check(data)

    def test_result_contains_no_source_or_reason_text(self):
        result = self.check()
        self.assertNotIn('node prerequisite', str(result))
        self.assertNotIn('assert False', str(result))


class RequiredNodeAdapterTests(unittest.TestCase):
    def adapt(self):
        from broker.framework_mark_diagnosis import adapt_required_node
        return adapt_required_node(SOURCE, hashlib.sha256(SOURCE).hexdigest())

    def suite(self, result):
        namespace = {}
        exec(compile(result, '<required-node-fixture>', 'exec'), namespace)
        return unittest.defaultTestLoader.loadTestsFromTestCase(namespace['DeliveryAdaptedTests'])

    def test_node_available_keeps_original_failing_assertion(self):
        from unittest.mock import patch
        result, receipt = self.adapt()
        with patch('shutil.which', return_value='/fixed/node'):
            outcome = unittest.TestResult()
            self.suite(result).run(outcome)
        self.assertEqual(len(outcome.failures), 1)
        self.assertFalse(outcome.errors)
        self.assertFalse(outcome.skipped)
        self.assertTrue(receipt['mandatory_node_preflight'])
        self.assertFalse(receipt['delivery_approval'])
        self.assertEqual(receipt['original_sha256'], hashlib.sha256(SOURCE).hexdigest())

    def test_missing_node_fails_instead_of_skipping(self):
        from unittest.mock import patch
        result, _ = self.adapt()
        with patch('shutil.which', return_value=None):
            outcome = unittest.TestResult()
            self.suite(result).run(outcome)
        self.assertEqual(len(outcome.errors), 1)
        self.assertIn('required node runtime unavailable', outcome.errors[0][1])
        self.assertFalse(outcome.skipped)

    def test_entire_test_bodies_and_helpers_remain_identical(self):
        import ast
        from surgical_test_edit import _tests, _discoverable
        result, receipt = self.adapt()
        before, after = ast.parse(SOURCE), ast.parse(result)
        self.assertEqual(_tests(before), _tests(after))
        self.assertEqual(ast.dump(before.body[2]), ast.dump(after.body[2]))
        _discoverable(after)
        self.assertTrue(receipt['test_bodies_preserved'])
        self.assertFalse(receipt['red_evidence'])

    def test_adapter_is_deterministic(self):
        self.assertEqual(self.adapt(), self.adapt())
