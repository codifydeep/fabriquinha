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

class StrengtheningTests(unittest.TestCase):
    def check(self,after):
        from fabriquinha.test_revision import strengthening_diff
        return strengthening_diff(BEFORE,after,cases=['Cancellation.test_full_room'],product_imports=['app'])

    def test_explicit_app_assertions_append_without_changing_old_statements(self):
        after=BEFORE+"        import app as rules\n        self.assertEqual(rules.compare_cards(('5','Hearts'),('5','Spades'),'5'), 'A')\n"
        self.assertTrue(self.check(after)['semantic_review_required'])
        with self.assertRaises(ValueError):technical_repair_diff(BEFORE,after)

    def test_rejects_weakened_old_assertion_and_shadowing_and_foreign_import(self):
        suffix="        import app as rules\n        self.assertEqual(rules.compare_cards(('5','Hearts'),('5','Spades'),'5'), 'A')\n"
        for after in (BEFORE.replace('409','200')+suffix,
                      BEFORE+suffix.replace('as rules','as self'),
                      BEFORE+suffix.replace('import app','import os'),
                      BEFORE+'        return\n'+suffix,
                      BEFORE+suffix+'        self.assertEqual = rules.compare_cards\n',
                      BEFORE+suffix.replace('rules.compare_cards','rules.__dict__.clear')):
            with self.subTest(after=after),self.assertRaises(ValueError):self.check(after)

class CumulativeStrengtheningTests(unittest.TestCase):
    def test_prior_added_assertions_are_protected_when_scope_grows(self):
        from fabriquinha.test_revision import cumulative_strengthening_diff
        first=BEFORE+"        import app as cards\n        self.assertEqual(cards.compare_cards(('5','Hearts'),('5','Spades'),'5'), 'A')\n"
        second=first+"        import app as outcome\n        self.assertEqual(outcome.hand_outcome(['T','A','B']), 'draw')\n"
        args=dict(cases=['Cancellation.test_full_room'],product_imports=['app'])
        cumulative_strengthening_diff(BEFORE,first,second,**args)
        with self.assertRaises(ValueError):
            cumulative_strengthening_diff(BEFORE,first,second.replace("        self.assertEqual(cards.compare_cards(('5','Hearts'),('5','Spades'),'5'), 'A')\n",''),**args)
