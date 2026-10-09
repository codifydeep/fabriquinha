import unittest
from browser_qa_recipes import LEGACY_SCENARIOS, DETAIL_SCENARIOS, COUNT_SCENARIOS, recipe_for, baseline_for


class FixedRecipeTests(unittest.TestCase):
    def test_legacy_recipe_is_preserved_and_bounded(self):
        self.assertEqual(len(LEGACY_SCENARIOS), 14)
        paths = {recipe_for(name) for name in LEGACY_SCENARIOS}
        self.assertEqual(len(paths), 1)
        recipe = paths.pop()
        self.assertEqual(recipe.name, 'browser_feedback_acceptance.py')
        self.assertLessEqual(len(recipe.read_bytes()), 32768)

    def test_details_require_an_independent_bounded_recipe_and_full_baseline(self):
        for name in DETAIL_SCENARIOS:
            recipe=recipe_for(name)
            self.assertEqual(recipe.name,'browser_feedback_detail.py')
            self.assertLessEqual(len(recipe.read_bytes()),32768)
            self.assertEqual(baseline_for(name),'feedback-board-demo-mode-ui-v1')
    def test_arbitrary_paths_fail_closed(self):
        for name in ('/tmp/scenario.py', '../scenario.py', 'shell', None, {}):
            with self.assertRaisesRegex(ValueError, 'unqualified'):
                recipe_for(name)

    def test_count_retains_detail_and_legacy_regressions(self):
        for name in COUNT_SCENARIOS:
            recipe=recipe_for(name)
            self.assertEqual(recipe.name,'browser_feedback_count.py')
            self.assertLessEqual(len(recipe.read_bytes()),32768)
            self.assertEqual(baseline_for(name),'feedback-board-detail-ui-v1')
            self.assertEqual(baseline_for(baseline_for(name)),'feedback-board-demo-mode-ui-v1')
