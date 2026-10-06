import hashlib
import unittest
from broker.test_first_protocol import _test_methods, SnapshotRejection, snapshot_rejection_error


class NewTestRejectionTests(unittest.TestCase):
    def test_nonempty_without_tests_is_a_hash_bound_rejection(self):
        data = b'# Documentation is not an executable test.\n'
        with self.assertRaises(SnapshotRejection) as raised: _test_methods('tests/test_new.py', data)
        receipt = raised.exception.receipt
        self.assertEqual(receipt['category'], 'new_test_no_methods')
        self.assertEqual(receipt['files']['tests/test_new.py'],
                         {'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()})
        self.assertEqual(snapshot_rejection_error(receipt), 'test-first NEW test has no executable test methods')

    def test_syntax_rejection_has_coordinates_never_source_excerpt(self):
        data = b'def test_invalid(:\n    pass\n'
        with self.assertRaises(SnapshotRejection) as raised: _test_methods('tests/test_new.py', data)
        receipt = raised.exception.receipt
        self.assertEqual(receipt['category'], 'new_test_syntax_error')
        self.assertEqual(receipt['files']['tests/test_new.py']['line'], 1)
        self.assertEqual(set(receipt['files']['tests/test_new.py']), {'bytes','sha256','line','offset'})
