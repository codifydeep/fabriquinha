import hashlib
import json
import unittest
from upstream_error_diagnostic import describe,UpstreamRequestRejected


class UpstreamErrorTests(unittest.TestCase):
    def test_only_fixed_markers_and_hash_leave_untrusted_provider_body(self):
        raw=json.dumps({'error':{'message':'SECRET-API-TOKEN tool_result missing tool_use in messages schema'}}).encode()
        result=describe(raw)
        self.assertEqual(result['response_sha256'],hashlib.sha256(raw).hexdigest())
        self.assertEqual(result['markers'],['messages','schema','tool_result','tool_use'])
        self.assertNotIn('SECRET',json.dumps(result))
        self.assertTrue(result['json_error'])
        error=UpstreamRequestRejected(raw)
        self.assertEqual(str(error),'upstream request rejected')
        self.assertEqual(error.status,400)

    def test_invalid_json_cannot_export_arbitrary_text_or_keys(self):
        for raw in (b'SECRET arbitrary response',b'[]',b'{"not_error":"tool_use"}'):
            result=describe(raw)
            self.assertFalse(result['json_error'])
            self.assertEqual(result['markers'],[])
            self.assertEqual(set(result),{'version','response_sha256','json_error','markers'})

    def test_nested_provider_body_exports_fixed_hints_not_metadata(self):
        raw=json.dumps({'error':{'message':'Provider returned error','metadata':{
            'raw':'PRIVATE-VALUE unsupported schema anyOf','provider_name':'PRIVATE-PROVIDER'}}}).encode()
        result=describe(raw)
        self.assertEqual(result['markers'],['anyof','schema','unsupported'])
        self.assertNotIn('PRIVATE',json.dumps(result))
