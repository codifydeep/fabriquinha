import copy
import unittest

from write_tool_schema import apply


class WriteToolSchemaTests(unittest.TestCase):
    def request(self):
        return {'messages': [], 'tools': [{'type': 'function', 'function': {
            'name': 'write_file', 'parameters': {'type': 'object', 'properties': {
                'path': {'type': 'string'}, 'content': {'type': 'string'}},
                'required': ['path', 'content']}}},
            {'type': 'function', 'function': {'name': 'terminal', 'parameters': {'type': 'object'}}}]}

    def test_requires_arguments_without_rewriting_calls_or_other_tools(self):
        body = self.request()
        original = copy.deepcopy(body)
        result = apply(body)
        self.assertEqual(body, original)
        function = result['tools'][0]['function']
        self.assertTrue(function['strict'])
        self.assertEqual(function['parameters']['required'], ['path', 'content'])
        self.assertFalse(function['parameters']['additionalProperties'])
        self.assertEqual(function['parameters']['properties']['path']['minLength'], 1)
        self.assertEqual(result['tools'][1], body['tools'][1])
        self.assertTrue(result['provider']['require_parameters'])
        self.assertEqual(apply(result), result)

    def test_unknown_signature_fails_closed(self):
        body = self.request()
        body['tools'][0]['function']['parameters']['properties']['file'] = {'type': 'string'}
        with self.assertRaisesRegex(ValueError, 'signature'):
            apply(body)

    def test_no_write_tool_leaves_request_unchanged(self):
        body = {'messages': []}
        self.assertIs(apply(body), body)

    def test_recovery_requires_actual_preapproval_path_error_not_a_permission_request(self):
        from resume_filter_write_schema import missing_write_path
        self.assertTrue(missing_write_path([{'type': 'tool_result', 'tool': 'write_file',
            'output': 'Edit approval denied: could not prepare diff (path required)'}]))
        for message in ({'type': 'text', 'output': 'path required'},
                        {'type': 'tool_result', 'tool': 'write_file',
                         'output': 'Edit approval denied by ACP client'},
                        {'type': 'tool_result', 'tool': 'terminal',
                         'output': 'could not prepare diff (path required)'}):
            self.assertFalse(missing_write_path([message]))
