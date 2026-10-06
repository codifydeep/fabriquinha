import asyncio
import json
import os
import unittest
from unittest.mock import Mock, patch
from broker import review_tool_policy as policy


class ReviewPolicyTests(unittest.TestCase):
    def test_additive_rejection_reason_survives_acp_error_field_without_private_details(self):
        cfg={'path':'/workspace/tests/test_new.py','criterion':'C01','sources':{}}
        with patch.dict(os.environ,{'DELIVERY_EXECUTION_MODE':'implementation',
                'DELIVERY_ADDITIVE_TEST_JSON':json.dumps(cfg)}),patch('additive_test_policy.write') as write:
            write.side_effect=ValueError('new file must contain imports and a TestCase only')
            result=json.loads(policy.controlled('write_file',{}))
            self.assertIn('imports and a TestCase only',result['error'])
            write.side_effect=ValueError('secret path /private/key')
            self.assertNotIn('secret',policy.controlled('write_file',{}))
            write.side_effect=PermissionError('private path')
            self.assertIn('workspace_permission_denied',json.loads(policy.controlled('write_file',{}))['error'])
    def test_surgical_handler_requires_actual_complete_read_and_denies_bypass(self):
        config={'path':'/workspace/test_new.py','expected_sha256':'a'*64}
        envelope={'expected_sha256':'a'*64,'edits':[{'old':'import pytest','new':'import unittest'}]}
        args={'path':config['path'],'content':json.dumps(envelope)}
        policy.SURGICAL_READ_PAGES.clear()
        with patch.dict(os.environ,{'DELIVERY_EXECUTION_MODE':'implementation',
                'DELIVERY_SURGICAL_TEST_JSON':json.dumps(config)}),patch('pathlib.Path.read_text',return_value='line1\nline2\n'),\
                patch('surgical_test_edit.edit_file') as edit:
            edit.side_effect=lambda *a,**kw: {'verified':kw['observed_read']}
            self.assertFalse(json.loads(policy.controlled('write_file',args))['verified'])
            read=policy.fence('read_file',Mock(return_value=json.dumps({'content':'1|line1','total_lines':2})))
            read({'path':config['path'],'offset':1,'limit':1})
            self.assertFalse(json.loads(policy.controlled('write_file',args))['verified'])
            read({'path':config['path'],'offset':2,'limit':1})
            self.assertTrue(json.loads(policy.controlled('write_file',args))['verified'])
            for name in ('terminal','patch_file','python','delegate_task'):
                original=Mock()
                self.assertIn('error',json.loads(policy.fence(name,original)({})))
                original.assert_not_called()
            self.assertIn('error',json.loads(policy.controlled('write_file',{**args,'path':'/workspace/app.py'})))

    def test_generic_python_terminal_and_edits_never_reach_handler(self):
        with patch.dict(os.environ, {'DELIVERY_EXECUTION_MODE': 'review'}):
            for name, args in [('python', {'code': 'print(1)'}),
                               ('terminal', {'command': 'id'}),
                               ('write_file', {'path': '/delivery/a', 'content': 'bad'}),
                               ('delegate_task', {}), ('read_file', {'path': '/delivery/../tmp/key'})]:
                handler = Mock()
                result = json.loads(policy.fence(name, handler)(args))
                self.assertIn('operation_forbidden', result['error'])
                handler.assert_not_called()

    def test_fixed_full_suite_calls_empty_rpc_and_no_selection_or_append_allowed(self):
        command = 'cd /workspace && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s . -q 2>&1'
        requested = command.replace('/workspace', '/delivery')
        with patch.dict(os.environ, {'DELIVERY_EXECUTION_MODE': 'review',
                                     'DELIVERY_REVIEW_SUITE_CAPABILITY': 'a' * 64,
                                     'DELIVERY_TEST_COMMANDS_JSON': json.dumps([command])}), \
                patch.object(policy.urllib.request, 'urlopen') as run:
            run.return_value.__enter__.return_value.read.return_value = json.dumps({
                'output': 'Ran 128 tests\nOK', 'exit_code': 0,
                'executed_by': 'controller_offline_review_suite',
                'network': 'none', 'snapshot_mount': 'readonly'}).encode()
            result = json.loads(policy.controlled('terminal', {'command': requested}))
            self.assertEqual(result['exit_code'], 0)
            request = run.call_args.args[0]
            self.assertEqual(request.full_url, 'http://execution-broker:8090/v1/review-suite')
            self.assertEqual(request.data, b'{}')
            for value in (requested + '; id', requested.replace('-s .', '-s tests'),
                          'python3 -c "print(1)"'):
                self.assertIn('error', json.loads(policy.controlled('terminal', {'command': value})))
            self.assertEqual(run.call_count, 1)

    def test_rpc_failure_or_missing_capability_never_executes_local_fallback(self):
        command = 'cd /workspace && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s . -q 2>&1'
        with patch.dict(os.environ, {'DELIVERY_EXECUTION_MODE': 'review',
                'DELIVERY_TEST_COMMANDS_JSON': json.dumps([command]),
                'DELIVERY_REVIEW_SUITE_CAPABILITY': ''}), \
                patch.object(policy.urllib.request, 'urlopen') as call:
            result = json.loads(policy.controlled('terminal', {'command': command.replace('/workspace','/delivery')}))
            self.assertEqual(result['error'], 'review_suite_capability_missing')
            call.assert_not_called()
            os.environ['DELIVERY_REVIEW_SUITE_CAPABILITY'] = 'a' * 64
            call.side_effect = TimeoutError('sensitive token information')
            result = json.loads(policy.controlled('terminal', {'command': command.replace('/workspace','/delivery')}))
            self.assertEqual(result, {'error': 'review_suite_infrastructure_failed', 'exit_code': 5})

    def test_planning_reads_only_evidence_and_async_handlers_also_fenced(self):
        with patch.dict(os.environ, {'DELIVERY_EXECUTION_MODE': 'planning'}):
            self.assertIsNone(policy.controlled('read_file', {'path': '/evidence/previous/tests/t.py'}))
            self.assertIn('error', json.loads(policy.controlled('read_file', {'path': '/session-state/key'})))
            async def forbidden(args, **kwargs):
                raise AssertionError('handler reached')
            result = asyncio.run(policy.fence('python', forbidden, True)({}))
            self.assertIn('error', json.loads(result))

    def test_implementation_behavior_unchanged(self):
        with patch.dict(os.environ, {'DELIVERY_EXECUTION_MODE': 'implementation'}):
            handler = Mock(return_value='original')
            self.assertEqual(policy.fence('python', handler)({}), 'original')
