import unittest
import audit_search_scope as audit


class ScopeTests(unittest.TestCase):
    def test_preamble_reads_literal_without_executing_source(self):
        self.assertEqual(audit.preamble("DRIVER_PREAMBLE='literal'\nraise Exception('not executed')"),'literal')

    def test_missing_duplicate_or_executable_harness_is_rejected(self):
        for text in ("OTHER='x'", "DRIVER_PREAMBLE='a'\nDRIVER_PREAMBLE='b'", "DRIVER_PREAMBLE=execute()"):
            with self.assertRaises(ValueError):audit.preamble(text)

    def test_same_view_race_driver_never_substitutes_product_source(self):
        self.assertIn('vm.runInContext(SOURCE, context',audit.DRIVER)
        self.assertIn('pending[0].url !== pending[1].url',audit.DRIVER)
        self.assertIn('resolveNewest',audit.DRIVER);self.assertIn('resolveOldest',audit.DRIVER)
        self.assertNotIn('SOURCE.replace',audit.DRIVER)
