import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock

import start_portable
from test_portable_contract import contract


class GenericDispatchTests(unittest.TestCase):
    def test_existing_planned_issue_is_reused_only_after_identity_gate(self):
        definition = contract()
        spec = {'label': 'FB-1', 'title': 'Planned C1',
                'description': 'Implement the validated card.',
                'review_instruction': 'Review the frozen delivery.',
                'implementer_registry': 'backend-agent.json',
                'reviewer_registry': 'review-agent.json', 'sha256': 'b' * 64}
        issue_id, base, plan_sha = '12345678-1234-1234-1234-123456789abc', 'a' * 40, 'c' * 64
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'backend-agent.json').write_text(json.dumps(
                {'agent_id': 'author', 'workspace_id': 'workspace'}))
            (root / 'review-agent.json').write_text(json.dumps(
                {'agent_id': 'reviewer', 'workspace_id': 'workspace'}))
            def client(*args):
                if args[:2] == ('metadata', 'list'):
                    return {'planning_sha256': plan_sha,
                            'execution_gate': 'awaiting_generated_contract'}
                if args[0] == 'get':
                    return {'id': issue_id, 'title': spec['title'],
                            'status': 'blocked', 'assignee_id': None}
                if args[:2] == ('wakeup', 'list'):
                    return []
                if args[0] == 'update':
                    return {'description': spec['description'], 'status': 'todo'}
                if args[0] == 'assign':
                    return {'assignee_id': 'author'}
                return {}
            with patch.dict(start_portable.os.environ, {
                    'DELIVERY_KIT_EXISTING_ISSUE_ID': issue_id,
                    'DELIVERY_KIT_EXPECTED_PLAN_SHA': plan_sha}), \
                    patch.object(start_portable, 'PRIVATE', root), \
                    patch.object(start_portable, 'from_environment', return_value=definition), \
                    patch.object(start_portable, 'selected_project', return_value={
                        'repository': definition['repository']}), \
                    patch.object(start_portable, 'load_run_spec', return_value=spec), \
                    patch.object(start_portable, 'issue') as create_issue, \
                    patch.object(start_portable, 'prepare', return_value={'base_sha': base}), \
                    patch.object(start_portable, 'verified_main', return_value=base), \
                    patch.object(start_portable, 'cli', side_effect=client) as mocked:
                start_portable.main()
            create_issue.assert_not_called()
            self.assertTrue(any(call.args[0] == 'update' for call in mocked.call_args_list))

    def test_spec_drives_intake_agents_review_and_context_without_real_dispatch(self):
        definition = contract()
        definition['repository'] = 'example/another-project'
        run_spec = {'label': 'DEMO-1', 'title': 'Generic feature',
                    'description': 'Implement and test a feature.',
                    'review_instruction': 'Review the frozen delivery.',
                    'implementer_registry': 'backend-agent.json',
                    'reviewer_registry': 'review-agent.json',
                    'sha256': 'b' * 64}
        issue_id, base = 'issue-1', 'a' * 40
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'backend-agent.json').write_text(json.dumps(
                {'agent_id': 'author', 'workspace_id': 'workspace'}))
            (root / 'review-agent.json').write_text(json.dumps(
                {'agent_id': 'reviewer', 'workspace_id': 'workspace'}))
            client = Mock(side_effect=lambda *args: (
                [] if args[:2] == ('wakeup', 'list') else
                {'assignee_id': 'author'} if args[0] == 'assign' else
                {'id': 'wakeup-1'}))
            with patch.object(start_portable, 'PRIVATE', root), \
                    patch.object(start_portable, 'from_environment', return_value=definition), \
                    patch.object(start_portable, 'selected_project', return_value={
                        'repository': definition['repository']}), \
                    patch.object(start_portable, 'load_run_spec', return_value=run_spec), \
                    patch.object(start_portable, 'issue', return_value={
                        'id': issue_id, 'assignee_id': None}) as create_issue, \
                    patch.object(start_portable, 'prepare', return_value={
                        'base_sha': base}), \
                    patch.object(start_portable, 'verified_main', return_value=base), \
                    patch.object(start_portable, 'cli', client):
                start_portable.main()
            create_issue.assert_called_once_with('Generic feature',
                                                 'Implement and test a feature.')
            created = [call.args for call in client.call_args_list
                       if call.args[:2] == ('wakeup', 'create')]
            self.assertEqual(len(created), 1)
            self.assertIn('Review the frozen delivery.', created[0])
            self.assertIn('reviewer', created[0])
            self.assertEqual(json.loads((root / 'portable-context-DEMO-1.json').read_text())
                             ['run_spec_sha256'], 'b' * 64)


if __name__ == '__main__':
    unittest.main()
