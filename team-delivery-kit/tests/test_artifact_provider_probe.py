import json
import unittest
from probe_test_artifact_provider import check_call


class ProviderProbeTests(unittest.TestCase):
    def call(self, name, args):
        return {'tool_calls': [{'id': 'synthetic', 'type': 'function',
                              'function': {'name': name, 'arguments': json.dumps(args)}}]}

    def test_bound_read_and_nonempty_write(self):
        check_call(self.call('read_file', dict(path='/workspace/app.py', offset=1, limit=50)), 'read')
        check_call(self.call('write_file', dict(path='/workspace/tests/test_new.py', content='test')), 'write')

    def test_prose_duplicate_or_wrong_target_cannot_pass(self):
        with self.assertRaises(ValueError): check_call({'content': 'I wrote it'}, 'write')
        body = self.call('write_file', dict(path='/workspace/app.py', content='test'))
        with self.assertRaises(ValueError): check_call(body, 'write')
        body = self.call('write_file', dict(path='/workspace/tests/test_new.py', content=''))
        with self.assertRaises(ValueError): check_call(body, 'write')
        body['tool_calls'] *= 2
        with self.assertRaises(ValueError): check_call(body, 'write')
