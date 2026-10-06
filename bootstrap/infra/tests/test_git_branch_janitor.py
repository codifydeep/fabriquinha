import importlib.util
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


MODULE_PATH = Path(__file__).resolve().parents[1] / "git_branch_janitor.py"
SPEC = importlib.util.spec_from_file_location("git_branch_janitor", MODULE_PATH)
janitor = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(janitor)


class GitBranchJanitorTests(unittest.TestCase):
    def test_changed_eligibility_prevents_cleanup(self):
        with TemporaryDirectory() as tmp, patch.object(janitor, 'candidates', return_value=([], [])), patch.object(janitor, 'command') as command:
            result = janitor.apply_cleanup(Path(tmp), [{'branch':'feat/t_deadbeef-x'}], Path(tmp)/'audit', db=Path(tmp)/'db', grace_seconds=0)
            self.assertEqual(result, [])
            command.assert_not_called()

    def test_remote_lease_failure_preserves_local_worktree(self):
        item = dict(branch='feat/t_deadbeef-x', task_id='t_deadbeef', sha='a'*40, remote=True, worktree='/not/deleted')
        calls = []
        def command(repo, *args, **kwargs):
            calls.append(args)
            if 'push' in args:
                raise RuntimeError('stale lease')
        with TemporaryDirectory() as tmp, patch.object(janitor, 'candidates', return_value=([item], [])), patch.object(janitor, 'command', command), patch('kanban_watchdog.scan_worker_processes', return_value={}):
            with self.assertRaises(RuntimeError):
                janitor.apply_cleanup(Path(tmp), [item], Path(tmp)/'audit', db=Path(tmp)/'db', grace_seconds=0)
            self.assertTrue(any('--force-with-lease=refs/heads/feat/t_deadbeef-x:'+'a'*40 in c for c in calls))
            self.assertFalse(any('remove' in c or '-d' in c for c in calls))
            self.assertIn('a'*40, (Path(tmp)/'audit').read_text())

    def test_protects_main_and_all_release_branches(self):
        self.assertTrue(janitor.protected("main"))
        self.assertTrue(janitor.protected("release/v0.1"))
        self.assertTrue(janitor.protected("release/hotfix"))
        self.assertFalse(janitor.protected("feat/t_deadbeef-x"))

    def test_extracts_task_id_only_from_task_branches(self):
        self.assertEqual(janitor.task_id_from_branch("feat/t_deadbeef-x"), "t_deadbeef")
        self.assertEqual(janitor.task_id_from_branch("wt/t_1234abcd"), "t_1234abcd")
        self.assertIsNone(janitor.task_id_from_branch("temp-adr"))


if __name__ == "__main__":
    unittest.main()
