import unittest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import release_eval


class ReleaseBridgeTests(unittest.TestCase):
    def test_approval_uses_authenticated_runtime_and_rejects_foreign_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'workspace.json').write_text(json.dumps({'id': 'workspace'}))
            for filename, agent in [('implementer.json', 'author'), ('reviewer.json', 'reviewer')]:
                (root / filename).write_text(json.dumps({'agent_id': agent, 'workspace_id': 'workspace'}))
            runs = [{'id': 'source', 'issue_id': 'issue', 'workspace_id': 'workspace',
                     'agent_id': 'author', 'status': 'completed', 'created_at': 'now'},
                    {'id': 'review', 'issue_id': 'issue', 'workspace_id': 'workspace',
                     'agent_id': 'reviewer', 'status': 'completed'}]
            row = ('review', 'source', 'reviewer', 'a' * 64, 'approved', 'snapshot', 'complete', 'author')
            with patch.object(release_eval, 'PRIVATE', root), \
                    patch.object(release_eval, 'json_command', side_effect=[runs, row]) as command:
                result = release_eval.approved_submission('issue')
                self.assertEqual(result['source_task'], 'source')
                self.assertEqual(command.call_args_list[0].args[:6],
                                 ('docker', 'exec', release_eval.PROJECT + '-runtime-1', 'multica', 'issue', 'runs'))
            runs[0]['workspace_id'] = 'foreign'
            with patch.object(release_eval, 'PRIVATE', root), patch.object(release_eval, 'json_command', return_value=runs):
                with self.assertRaisesRegex(ValueError, 'invalid issue runs'):
                    release_eval.approved_submission('issue')
    def test_ci_gate_rejects_moved_head(self):
        pr = {'state': 'OPEN', 'headRefOid': 'b' * 40, 'baseRefOid': 'c' * 40,
              'mergeStateStatus': 'CLEAN', 'statusCheckRollup': [{'name': 'ci', 'conclusion': 'SUCCESS'}]}
        with patch.object(release_eval, 'json_command', return_value=pr):
            with self.assertRaisesRegex(ValueError, 'identity or base moved'):
                release_eval.wait_pr_ci(6, 'a' * 40, 'c' * 40, timeout=1)

    def test_ci_gate_rejects_failure(self):
        pr = {'state': 'OPEN', 'headRefOid': 'a' * 40, 'baseRefOid': 'c' * 40,
              'mergeStateStatus': 'BLOCKED', 'statusCheckRollup': [{'name': 'ci', 'conclusion': 'FAILURE'}]}
        with patch.object(release_eval, 'json_command', return_value=pr):
            with self.assertRaisesRegex(ValueError, 'required CI failed'):
                release_eval.wait_pr_ci(6, 'a' * 40, 'c' * 40, timeout=1)

    def test_ci_gate_accepts_only_clean_exact_head(self):
        pr = {'state': 'OPEN', 'headRefOid': 'a' * 40, 'baseRefOid': 'c' * 40,
              'mergeStateStatus': 'CLEAN', 'statusCheckRollup': [{'name': 'ci', 'conclusion': 'SUCCESS'}]}
        with patch.object(release_eval, 'json_command', return_value=pr):
            self.assertEqual(release_eval.wait_pr_ci(6, 'a' * 40, 'c' * 40, timeout=1), pr)
