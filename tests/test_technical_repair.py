"""Technical repair evidence must not grant authority or weaken assertions."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from fabriquinha.test_revision import technical_repair_diff

BEFORE = '''class Cancellation(TestCase):
    def test_full_room(self):
        result = page.evaluate(script)
        self.assertEqual(result['status'], 409)
        self.assertEqual(errors, [])
'''


class TechnicalRepairTests(unittest.TestCase):
    def test_action_can_change_without_changing_assertions(self):
        after = BEFORE.replace('page.evaluate(script)', 'creator_request(page.context)')
        self.assertTrue(technical_repair_diff(BEFORE, after)['semantic_review_required'])

    def test_same_assertion_count_cannot_hide_weaker_expectations(self):
        for after in (BEFORE.replace('409', '200'),
                      BEFORE.replace("self.assertEqual(result['status'], 409)", 'self.assertTrue(True)'),
                      BEFORE.replace('self.assertEqual(errors, [])', 'self.assertEqual([], [])')):
            with self.subTest(after=after), self.assertRaises(ValueError):
                technical_repair_diff(BEFORE, after)

    def test_assertion_cannot_be_moved_under_conditional(self):
        after = BEFORE.replace('        self.assertEqual(errors, [])',
                               '        if False:\n            self.assertEqual(errors, [])')
        with self.assertRaises(ValueError):
            technical_repair_diff(BEFORE, after)

    def test_existing_condition_cannot_silence_assertion(self):
        before=BEFORE.replace('        self.assertEqual(errors, [])',
                              '        if observe:\n            self.assertEqual(errors, [])')
        with self.assertRaises(ValueError):
            technical_repair_diff(before,before.replace('if observe:', 'if False:'))

    def test_scope_does_not_authorize_neighboring_case_or_harness(self):
        before=BEFORE+'    def test_other(self):\n        self.assertEqual(other(), 1)\n'
        for after in (before.replace('other()', 'constant_one()'),
                      before.replace('class Cancellation(TestCase):', 'class Cancellation(OtherHarness):'),
                      before.replace('        result =', '        return\n        result =')):
            with self.subTest(after=after),self.assertRaises(ValueError):
                technical_repair_diff(before,after,cases=['Cancellation.test_full_room'])

    def test_scoped_action_preserves_unrelated_case(self):
        before=BEFORE+'    def test_other(self):\n        self.assertEqual(other(), 1)\n'
        result=technical_repair_diff(before,before.replace('page.evaluate(script)', 'page.context.request.post(url)'),
                                    cases=['Cancellation.test_full_room'])
        self.assertTrue(result['semantic_review_required'])


if __name__ == '__main__':
    unittest.main()
