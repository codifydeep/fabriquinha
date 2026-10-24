import unittest
from provider_credit_diagnostic import summarize, PROGRAM


class DiagnosticTests(unittest.TestCase):
    def test_unlimited_key_does_not_resolve_pause(self):
        result=summarize(dict(total_credits=5,total_usage=4.32),dict(limit=None,limit_remaining=None))
        self.assertAlmostEqual(result['account_balance_usd'],.68)
        self.assertTrue(result['key_unlimited'])
        self.assertFalse(result['pause_removed'])
        self.assertEqual(result['model_calls'],0)

    def test_exhausted_key_is_reported_not_repaired(self):
        result=summarize(dict(total_credits=5,total_usage=1),dict(limit=1,limit_remaining=0))
        self.assertEqual(result['key_remaining_usd'],0)

    def test_invalid_numbers_and_missing_fields_rejected(self):
        for value in (True,float('nan'),float('inf'),-1,None):
            with self.subTest(value=value),self.assertRaises(ValueError):
                summarize(dict(total_credits=value,total_usage=0),dict(limit=None,limit_remaining=None))
        with self.assertRaises(ValueError):
            summarize(dict(total_credits=1,total_usage=0),{})

    def test_probe_has_no_mutation_or_model_endpoint(self):
        for prohibited in ('unlink(', 'reserve_call(', 'chat/completions', 'write_text(', 'os.open('):
            self.assertNotIn(prohibited,PROGRAM)
        self.assertIn('NoRedirect',PROGRAM)
        compile(PROGRAM,'diagnostic','exec')
