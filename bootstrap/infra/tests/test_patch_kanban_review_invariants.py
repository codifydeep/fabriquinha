import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "patches"
    / "patch_kanban_review_invariants.py"
)
SPEC = importlib.util.spec_from_file_location(
    "patch_kanban_review_invariants", MODULE_PATH
)
hotfix = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(hotfix)


class ReviewInvariantPatchTests(unittest.TestCase):
    def test_patch_is_exact_and_idempotent(self):
        source = (
            "before\n"
            + hotfix.OLD_RUNNING_GUARD
            + "middle\n"
            + hotfix.OLD_REVIEWER_CANONICALIZATION
            + "after\n"
        )

        patched = hotfix.apply_hotfix(source)

        self.assertIn(hotfix.NEW_RUNNING_GUARD, patched)
        self.assertIn(hotfix.NEW_REVIEWER_CANONICALIZATION, patched)
        self.assertEqual(hotfix.apply_hotfix(patched), patched)

    def test_patch_refuses_unknown_vendor_source(self):
        with self.assertRaises(SystemExit):
            hotfix.apply_hotfix("unexpected vendor source")


if __name__ == "__main__":
    unittest.main()
