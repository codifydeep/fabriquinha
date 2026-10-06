import ast
import hashlib
import unittest

from broker.framework_adapter import adapt


class FrameworkAdapterTests(unittest.TestCase):
    def adapt(self, source):
        data = source.encode()
        return adapt(data, hashlib.sha256(data).hexdigest())

    def test_plain_functions_preserve_names_bodies_and_helpers(self):
        source = 'import pytest\nX = 2\ndef helper():\n    return X\ndef test_value():\n    assert helper() == 2\n'
        result, receipt = self.adapt(source)
        before, after = ast.parse(source), ast.parse(result)
        old = before.body[-1]
        new = after.body[-1].body[0]
        self.assertEqual(old.name, new.name)
        self.assertEqual(ast.dump(ast.Module(body=old.body, type_ignores=[])),
                         ast.dump(ast.Module(body=new.body, type_ignores=[])))
        self.assertTrue(receipt['test_bodies_preserved'])
        self.assertFalse(receipt['delivery_approval'])
        self.assertFalse(receipt['red_evidence'])
        self.assertEqual(receipt['removed_unused_framework_imports'], 1)

    def test_deterministic_and_hash_bound(self):
        source = b'def test_value():\n    assert 1 == 1\n'
        digest = hashlib.sha256(source).hexdigest()
        self.assertEqual(adapt(source, digest), adapt(source, digest))
        with self.assertRaisesRegex(ValueError, '^adapter_source_drift$'):
            adapt(source, '0' * 64)

    def test_module_skip_mark_is_not_removed(self):
        with self.assertRaisesRegex(ValueError, '^adapter_framework_behavior$'):
            self.adapt('import pytest\npytestmark = pytest.mark.skipif(True, reason="x")\ndef test_value():\n    assert False\n')

    def test_fixtures_decorators_and_async_are_rejected(self):
        for source in ('def test_value(tmp_path):\n    assert tmp_path\n',
                       '@fixture\ndef test_value():\n    assert True\n',
                       'async def test_value():\n    assert True\n'):
            with self.subTest(source=source), self.assertRaises(ValueError):
                self.adapt(source)

    def test_binding_sensitive_bodies_are_rejected(self):
        for expression in ('locals()', 'globals()', 'self', 'test_value()', 'eval("1")'):
            with self.subTest(expression=expression), self.assertRaises(ValueError):
                self.adapt('def test_value():\n    assert ' + expression + '\n')

    def test_existing_unittest_binding_and_class_collisions_are_rejected(self):
        for prefix in ('unittest = 1\n', 'DeliveryAdaptedTests = 1\n'):
            with self.subTest(prefix=prefix), self.assertRaises(ValueError):
                self.adapt(prefix + 'def test_value():\n    assert True\n')

    def test_nested_tests_are_rejected(self):
        with self.assertRaises(ValueError):
            self.adapt('def helper():\n    def test_hidden():\n        assert False\ndef test_value():\n    assert True\n')

    def test_alias_unused_import_is_removed_but_used_alias_rejected(self):
        _, receipt = self.adapt('import pytest as p\ndef test_value():\n    assert True\n')
        self.assertEqual(receipt['removed_unused_framework_imports'], 1)
        with self.assertRaisesRegex(ValueError, '^adapter_framework_behavior$'):
            self.adapt('import pytest as p\ndef test_value():\n    assert p.approx(1) == 1\n')

    def test_output_is_actually_unittest_discoverable(self):
        result, _ = self.adapt('def test_value():\n    assert 1 == 1\n')
        namespace = {}
        exec(compile(result, '<adapter-fixture>', 'exec'), namespace)
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(namespace['DeliveryAdaptedTests'])
        self.assertEqual(suite.countTestCases(), 1)
        outcome = unittest.TestResult()
        suite.run(outcome)
        self.assertTrue(outcome.wasSuccessful())

    def test_failing_assertion_still_fails_after_adaptation(self):
        result, _ = self.adapt('def test_value():\n    assert False, "unchanged failure"\n')
        namespace = {}
        exec(compile(result, '<adapter-fixture>', 'exec'), namespace)
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(namespace['DeliveryAdaptedTests'])
        outcome = unittest.TestResult()
        suite.run(outcome)
        self.assertEqual(len(outcome.failures), 1)
        self.assertIn('unchanged failure', outcome.failures[0][1])

    def test_duplicate_names_cannot_hide_a_test(self):
        with self.assertRaisesRegex(ValueError, '^adapter_duplicate_test_names$'):
            self.adapt('def test_value():\n    assert False\ndef test_value():\n    assert True\n')

    def test_future_import_remains_valid_and_all_tests_discovered(self):
        result, receipt = self.adapt('"doc"\nfrom __future__ import annotations\ndef test_a():\n    assert True\ndef test_b():\n    assert True\n')
        namespace = {}
        exec(compile(result, '<adapter-fixture>', 'exec'), namespace)
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(namespace['DeliveryAdaptedTests'])
        self.assertEqual(suite.countTestCases(), 2)
        self.assertEqual(receipt['test_count'], 2)
