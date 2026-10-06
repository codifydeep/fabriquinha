import unittest
from broker.maintenance_snapshot_validate import preserve_line_window


class C10ScopeTests(unittest.TestCase):
    def test_variable_length_c10_replacement_preserves_prefix_and_suffix(self):
        seed=b'C09 verified\nC10 old\nC10 old2\nprotected tests\n'
        self.assertTrue(preserve_line_window(seed,b'C09 verified\nnew C10\nmore C10\nextra C10\nprotected tests\n',2,3))

    def test_c09_or_assertion_suffix_change_is_rejected(self):
        seed=b'C09 verified\nC10 old\nC10 old2\nprotected tests\n'
        for candidate in (seed.replace(b'C09 verified',b'C09 changed'),seed.replace(b'protected tests',b'weakened tests')):
            with self.assertRaises(ValueError):preserve_line_window(seed,candidate,2,3)
        with self.assertRaises(ValueError):preserve_line_window(seed,seed)
