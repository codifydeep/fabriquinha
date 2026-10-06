import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import autonomous_eval


def run(*args, cwd):
    return subprocess.check_output(['git', '-C', str(cwd), *args], text=True).strip()


class AutonomousEvalTests(unittest.TestCase):
    def test_eval16_is_fixed_to_absolute_and_separate_qa_slot(self):
        self.assertEqual(autonomous_eval.CONFIGS['EVAL-16'],
                         ('absolute', {'test_absolute_positive', 'test_absolute_negative'}, 6))

    def test_eval18_is_fixed_to_double_and_separate_qa_slot(self):
        self.assertEqual(autonomous_eval.CONFIGS['EVAL-18'],
                         ('double', {'test_double_positive', 'test_double_negative'}, 7))
        self.assertEqual(autonomous_eval.CONFIGS['EVAL-19'],
                         ('double', {'test_double_positive', 'test_double_negative'}, 7))

    def test_branch_is_created_from_exact_base_and_reused(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            bare, repo = root / 'origin.git', root / 'repo'
            subprocess.run(['git', 'init', '--bare', str(bare)], check=True, capture_output=True)
            subprocess.run(['git', 'init', '-b', 'main', str(repo)], check=True, capture_output=True)
            run('config', 'user.name', 'Evaluation', cwd=repo)
            run('config', 'user.email', 'eval@example.invalid', cwd=repo)
            run('remote', 'add', 'origin', str(bare), cwd=repo)
            for name, content in {'AGENTS.md': 'rules\n', 'calc.py': 'def add(a,b): return a+b\n',
                                  'test_calc.py': 'def test_add(): pass\n'}.items():
                (repo / name).write_text(content)
            run('add', '.', cwd=repo)
            run('commit', '-m', 'base', cwd=repo)
            run('push', '-u', 'origin', 'main', cwd=repo)
            base = run('rev-parse', 'main', cwd=repo)
            files = {'AGENTS.md': (repo / 'AGENTS.md').read_bytes(),
                     'calc.py': b'def add(a,b): return a+b\ndef negate(x): return -x\n',
                     'test_calc.py': b'def test_add(): pass\ndef test_negate(): pass\n'}
            with patch.object(autonomous_eval, 'REPO', repo):
                first = autonomous_eval.ensure_branch('codex/eval-15-reviewed', base, files)
                second = autonomous_eval.ensure_branch('codex/eval-15-reviewed', base, files)
            self.assertEqual(first, second)
            self.assertEqual(run('rev-parse', first + '^', cwd=repo), base)
            self.assertEqual(run('rev-parse', 'main', cwd=repo), base)
            self.assertEqual(run('ls-remote', 'origin', 'refs/heads/codex/eval-15-reviewed', cwd=repo).split()[0], first)

    def test_receipt_crash_is_durable_and_resume_does_not_reinject(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'state.json'
            state = {'identifier': 'EVAL-15'}
            with patch.dict('os.environ', {'EVAL_INJECT_AFTER': 'pr_open'}):
                with self.assertRaises(autonomous_eval.InjectedCrash):
                    autonomous_eval.persist(path, state, 'pr_open')
            self.assertEqual(json.loads(path.read_text())['stage'], 'pr_open')

    def test_existing_pr_is_reused_without_creation(self):
        pr = {'number': 8, 'state': 'OPEN', 'headRefOid': 'a' * 40,
              'baseRefOid': 'b' * 40, 'url': 'https://github.com/codifydeep/descartavel/pull/8'}
        with patch.object(autonomous_eval, 'json_command', return_value=[pr]), \
                patch.object(autonomous_eval, 'command') as create:
            self.assertEqual(autonomous_eval.ensure_pr('codex/eval-15-reviewed',
                                                        'a' * 40, 'b' * 40,
                                                        {'source_task': 'source', 'review_task': 'review',
                                                         'manifest_sha256': 'c' * 64}), pr)
            create.assert_not_called()

    def test_exhausted_review_is_escalated_instead_of_waiting_forever(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            (root / 'reviewer.json').write_text(json.dumps({'agent_id': 'reviewer'}))
            runs = [{'id': 'review-task', 'agent_id': 'reviewer',
                     'created_at': '2026-09-28T19:00:00Z'}]
            with patch.object(autonomous_eval, 'PRIVATE', root), \
                 patch.object(autonomous_eval.release_eval, 'approved_submission',
                              side_effect=ValueError('expected one approved exact revision')), \
                 patch.object(autonomous_eval, 'cli', return_value=runs), \
                 patch.object(autonomous_eval.subprocess, 'check_output',
                              return_value='{"incident":["review decision missing", "escalation_required"],"handoff":null}'):
                with self.assertRaisesRegex(ValueError, 'review escalation'):
                    autonomous_eval.approved('issue')

    def test_exhausted_change_handoff_is_escalated_instead_of_waiting_forever(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            (root / 'reviewer.json').write_text(json.dumps({'agent_id': 'reviewer'}))
            runs = [{'id': 'review-task', 'agent_id': 'reviewer',
                     'created_at': '2026-09-28T19:00:00Z'}]
            with patch.object(autonomous_eval, 'PRIVATE', root), \
                 patch.object(autonomous_eval.release_eval, 'approved_submission',
                              side_effect=ValueError('expected one approved exact revision')), \
                 patch.object(autonomous_eval, 'cli', return_value=runs), \
                 patch.object(autonomous_eval.subprocess, 'check_output',
                              return_value='{"incident":null,"handoff":["repeated_change_requests_escalate",2]}'):
                with self.assertRaisesRegex(ValueError, 'change handoff escalation'):
                    autonomous_eval.approved('issue')

    def test_historical_main_ci_is_tied_to_requested_sha(self):
        old = 'a' * 40
        runs = {'workflow_runs': [
            {'head_sha': 'b' * 40, 'event': 'push',
             'path': '.github/workflows/ci.yml', 'conclusion': 'success',
             'html_url': 'wrong'},
            {'head_sha': old, 'event': 'push',
             'path': '.github/workflows/ci.yml', 'conclusion': 'success',
             'html_url': 'https://example.invalid/exact'}]}
        with patch.object(autonomous_eval, 'json_command', return_value=runs):
            self.assertEqual(autonomous_eval.wait_exact_main_ci(old, timeout=1),
                             'https://example.invalid/exact')

    def test_board_receipt_uses_metadata_not_comment_wakeup(self):
        sha = 'a' * 40
        receipt = {'merge_sha': sha, 'delivery': {'manifest_sha256': 'b' * 64},
                   'pr_url': 'https://example.invalid/pr',
                   'main_ci_run': 'https://example.invalid/ci',
                   'deployment': {'url': 'http://127.0.0.1:19307', 'post_deploy_qa_cases': 13}}
        calls = []
        def fake_cli(*args):
            calls.append(args)
            if args[:2] == ('metadata', 'list'):
                return {}
            if args[0] == 'get':
                return {'status': 'in_progress'}
            if args[0] == 'status':
                return {'status': 'done'}
            return {}
        with patch.object(autonomous_eval, 'cli', side_effect=fake_cli):
            result = autonomous_eval.publish_board_receipt('issue', receipt)
        self.assertEqual(result, {'status': 'done', 'receipt_sha': sha,
                                  'storage': 'issue_metadata'})
        self.assertEqual(len([call for call in calls if call[:2] == ('metadata', 'set')]), 6)
        self.assertFalse(any(call[0] == 'comment' for call in calls))


if __name__ == '__main__':
    unittest.main()
