import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('transport', Path(__file__).parents[1] / 'broker/acp_transport.py')
transport = importlib.util.module_from_spec(spec)
spec.loader.exec_module(transport)


class ACPTests(unittest.TestCase):
    def test_structured_worker_failure_categories_do_not_expose_stderr(self):
        secret='PRIVATE PROVIDER BODY'
        labels=transport.failure_diagnostics(('RuntimeError: hermes_run_failed:iteration_budget_exhausted\n'+secret).encode())
        self.assertIn('iteration_budget_exhausted',labels)
        self.assertNotIn(secret,str(labels))
        self.assertEqual(transport.failure_diagnostics(b'RuntimeError: hermes_executor_failed'),['worker_executor_error'])
        self.assertEqual(transport.failure_diagnostics(b'RuntimeError: hermes_run_failed:agent_exception'),['worker_agent_exception'])
        self.assertEqual(transport.failure_diagnostics(b'private unclassified detail'),[])
    def test_model_environment_carries_execution_identity_without_secrets(self):
        identifier = '12345678-1234-1234-1234-123456789abc'
        env = transport.worker_env('planning', True, execution_id=identifier)
        self.assertIn('DELIVERY_MODEL_EXECUTION_ID='+identifier, env)
        self.assertIn('OPENROUTER_BASE_URL=http://model-proxy:8080/executions/'+identifier+'/api/v1', env)
        with self.assertRaises(ValueError):
            transport.worker_env('planning', True, execution_id='../secret')
    def test_review_rpc_capability_is_execution_scoped_not_implementation_environment(self):
        value = 'a' * 64
        self.assertIn('DELIVERY_REVIEW_SUITE_CAPABILITY=' + value,
                      transport.worker_env('review', True, review_suite_capability=value))
        for mode in ('implementation', 'planning'):
            with self.assertRaises(ValueError):
                transport.worker_env(mode, True, review_suite_capability=value)
    def test_only_implementation_can_write_inside_task_workspace(self):
        implementer = transport.worker_env('implementation', True)
        reviewer = transport.worker_env('review', True)
        planner = transport.worker_env('planning', True)
        self.assertIn('HERMES_WRITE_SAFE_ROOT=/workspace', implementer)
        self.assertNotIn('HERMES_WRITE_SAFE_ROOT=/workspace', reviewer)
        self.assertNotIn('HERMES_WRITE_SAFE_ROOT=/workspace', planner)
        self.assertIn('DELIVERY_EXECUTION_MODE=review', reviewer)
        self.assertIn('DELIVERY_EXECUTION_MODE=planning', planner)
        self.assertIn('OPENROUTER_API_KEY=' + transport.PLACEHOLDER_KEY, implementer)

    def test_edit_permission_is_once_and_task_scoped(self):
        def request(path):
            return {'jsonrpc': '2.0', 'id': 7, 'method': 'session/request_permission',
                    'params': {'options': [{'optionId': 'allow_once', 'kind': 'allow_once'},
                                           {'optionId': 'deny', 'kind': 'reject_once'}],
                               'toolCall': {'title': 'Approve edit: ' + path, 'kind': 'edit',
                                            'content': [{'type': 'diff', 'path': path}]}}}
        editable = {'/workspace/test_calc.py'}
        allowed = transport.permission_response(request('/workspace/test_calc.py'), 'implementation', editable)
        self.assertEqual(allowed['result']['outcome']['optionId'], 'allow_once')
        nested = transport.permission_response(request('/workspace/slug_tests/test_unicode.py'),
                                               'implementation', {'/workspace/slug_tests/test_unicode.py'})
        self.assertEqual(nested['result']['outcome']['optionId'], 'allow_once')
        for path in ('/delivery/artifact.txt', '/workspace/../delivery/artifact.txt',
                     '/workspace/AGENTS.md'):
            denied = transport.permission_response(request(path), 'implementation', editable)
            self.assertEqual(denied['result']['outcome']['optionId'], 'deny')
        denied = transport.permission_response(request('/workspace/calc.py'), 'review',
                                               {'/workspace/calc.py'})
        self.assertEqual(denied['result']['outcome']['optionId'], 'deny')
        denied = transport.permission_response(request('/workspace/calc.py'), 'planning',
                                               {'/workspace/calc.py'})
        self.assertEqual(denied['result']['outcome']['optionId'], 'deny')
        malformed = request('/workspace/calc.py')
        malformed['params']['options'] = [{'optionId': 'allow_always', 'kind': 'allow_always'}]
        self.assertIn('error', transport.permission_response(malformed, 'implementation'))

    def test_only_exact_pinned_test_command_is_approved_once(self):
        command = ('cd /workspace && PYTHONDONTWRITEBYTECODE=1 '
                   'python3 -m unittest discover -s slug_tests -q 2>&1')
        def request(value):
            return {'jsonrpc': '2.0', 'id': 8, 'method': 'session/request_permission',
                    'params': {'options': [{'optionId': 'allow_once', 'kind': 'allow_once'},
                                           {'optionId': 'deny', 'kind': 'reject_once'}],
                               'toolCall': {'title': 'Run tests: ' + value,
                                            'kind': 'execute',
                                            'rawInput': {'command': value},
                                            'content': [{'type': 'content', 'content':
                                                         {'type': 'text', 'text': '$ ' + value}}]}}}
        approved = transport.permission_response(request(command), 'implementation',
                                                 test_commands={command})
        self.assertEqual(approved['result']['outcome']['optionId'], 'allow_once')
        for value in (command + '; id', command.replace('slug_tests', '.'),
                      'cd /workspace && python3 -m unittest -q'):
            denied = transport.permission_response(request(value), 'implementation',
                                                   test_commands={command})
            self.assertEqual(denied['result']['outcome']['optionId'], 'deny')
        denied = transport.permission_response(request(command), 'review',
                                               test_commands={command})
        self.assertEqual(denied['result']['outcome']['optionId'], 'deny')
        denied = transport.permission_response(request(command), 'planning',
                                               test_commands={command})
        self.assertEqual(denied['result']['outcome']['optionId'], 'deny')

    def test_only_qualified_methods(self):
        for method in ('initialize', 'session/new', 'session/resume'):
            transport.validate_frame({'jsonrpc': '2.0', 'id': 1, 'method': method})
        for method in ('terminal/create', 'fs/write_text_file'):
            with self.assertRaises(ValueError):
                transport.validate_frame({'jsonrpc': '2.0', 'id': 1, 'method': method})
        transport.validate_frame({'jsonrpc': '2.0', 'id': 2, 'method': 'session/set_model',
                                  'params': {'sessionId': 's', 'modelId': transport.MODEL}})
        transport.validate_frame({'jsonrpc': '2.0', 'id': 3, 'method': 'session/prompt',
                                  'params': {'sessionId': 's', 'prompt': [{'type': 'text', 'text': 'hi'}]}})
        with self.assertRaises(ValueError):
            transport.validate_frame({'jsonrpc': '2.0', 'id': 4, 'method': 'session/new',
                                      'params': {'model': 'unapproved'}})
        with self.assertRaises(ValueError):
            transport.validate_frame({'jsonrpc': '2.0', 'id': 5, 'method': 'session/prompt',
                                      'params': {'sessionId': 's', 'prompt': [{'type': 'image', 'url': 'x'}]}})

    def test_unknown_fields_and_missing_identity(self):
        for frame in ({}, {'jsonrpc': '2.0', 'method': 'initialize'},
                      {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'command': 'id'}):
            with self.assertRaises(ValueError):
                transport.validate_frame(frame)
