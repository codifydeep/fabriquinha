import unittest
from browser_qa_recipes import LEGACY_SCENARIOS, recipe_for


class FixedRecipeTests(unittest.TestCase):
    def test_legacy_recipe_is_preserved_and_bounded(self):
        self.assertEqual(len(LEGACY_SCENARIOS), 14)
        paths = {recipe_for(name) for name in LEGACY_SCENARIOS}
        self.assertEqual(len(paths), 1)
        recipe = paths.pop()
        self.assertEqual(recipe.name, 'browser_feedback_acceptance.py')
        self.assertLessEqual(len(recipe.read_bytes()), 32768)

    def test_unqualified_details_and_arbitrary_paths_fail_closed(self):
        for name in ('feedback-board-detail-api-v1', 'feedback-board-detail-ui-v1',
                     '/tmp/scenario.py', '../scenario.py', 'shell', None, {}):
            with self.assertRaisesRegex(ValueError, 'unqualified'):
                recipe_for(name)
