import unittest
from broker.create_refresh_experiment import change, ANCHOR, REPLACEMENT


class CreateRefreshExperimentTests(unittest.TestCase):
    def test_only_settles_actual_refresh_without_fabricating_response_rows(self):
        body = 'existing query observations\n' + ANCHOR + '\nexisting assertions'
        self.assertEqual(change(body), body.replace(ANCHOR, REPLACEMENT))
        self.assertIn('resolveNewest();', change(body))
        self.assertNotIn('alpha new', REPLACEMENT)
        self.assertNotIn('deferred.push', REPLACEMENT)

    def test_missing_duplicate_or_already_changed_anchor_is_not_repaired(self):
        for body in ('', ANCHOR * 2, REPLACEMENT, None):
            with self.assertRaises(ValueError):
                change(body)
