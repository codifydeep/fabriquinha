import copy
import json
import unittest

from test_artifact_schema import apply


class TestArtifactSchemaTests(unittest.TestCase):
    def revision_history(self):
        body=self.body(read=True)
        body['messages'][0]['content']+='DELIVERY_TEST_REVISION_V1:/workspace/tests/test_new.py\n'
        body['messages'] += [{'role':'assistant','tool_calls':[{'id':'historic','function':{
            'name':'read_file','arguments':json.dumps({'path':'/workspace/tests/test_new.py','offset':1,'limit':50})}}]},
            {'role':'tool','tool_call_id':'historic','content':json.dumps({'content':'1|def test_old(): assert False','total_lines':1})}]
        return body

    def test_revision_write_advances_after_real_read_before_mutation(self):
        body=self.revision_history();content='def test_old():\n    assert 1 == 2\n'
        self.add_write(body,{'bytes_written':len(content.encode()),'verified':True},content)
        body['messages'] += [{'role':'assistant','tool_calls':[{'id':'changed','function':{
            'name':'read_file','arguments':json.dumps({'path':'/workspace/tests/test_new.py','offset':1,'limit':50})}}]},
            {'role':'tool','tool_call_id':'changed','content':json.dumps({'content':'1|def test_old():\n2|    assert 1 == 2','total_lines':2})}]
        self.assertIs(apply(body),body)

    def test_revision_failed_write_or_uninspected_target_does_not_advance(self):
        for inspected in (True,False):
            body=self.revision_history()
            if not inspected:body['messages']=body['messages'][:-2]
            content='def test_old(): assert False\n'
            self.add_write(body,{'bytes_written':len(content.encode()),'verified':not inspected},content)
            result=apply(body)
            self.assertIsNot(result,body)
            if not inspected:self.assertEqual(result['tool_choice']['function']['name'],'read_file')

    def surgical_body(self):
        body=self.body(read=True)
        body['messages'][0]['content']+='DELIVERY_SURGICAL_TEST_V1:/workspace/tests/test_new.py:'+'a'*64+'\n'
        return body

    def test_surgical_mode_requires_test_read_then_json_edit_not_bootstrap(self):
        body=self.surgical_body()
        first=apply(body)
        self.assertEqual(first['tool_choice']['function']['name'],'read_file')
        self.assertEqual(first['tools'][0]['function']['parameters']['properties']['path']['enum'],['/workspace/tests/test_new.py'])
        body['messages'] += [{'role':'assistant','tool_calls':[{'id':'target-read','function':{
            'name':'read_file','arguments':json.dumps({'path':'/workspace/tests/test_new.py','offset':1,'limit':50})}}]},
            {'role':'tool','tool_call_id':'target-read','content':json.dumps({'content':'1|def test_x(): assert False','total_lines':1})}]
        result=apply(body)
        self.assertEqual(result['tool_choice']['function']['name'],'write_file')
        self.assertIn('JSON envelope, NOT Python',result['messages'][-1]['content'])
        self.assertNotIn('FIRST ARTIFACT PHASE',result['messages'][-1]['content'])
        self.assertEqual(result['tools'][1]['function']['parameters']['properties']['content']['maxLength'],16384)

    def test_surgical_grant_does_not_reuse_prior_session_reads(self):
        body=self.body(read=True)
        body['messages'].append({'role':'user','content':
            'DELIVERY_SURGICAL_TEST_V1:/workspace/tests/test_new.py:'+'a'*64+'\n'})
        result=apply(body)
        self.assertEqual(result['tools'][0]['function']['parameters']['properties']['path']['enum'],['/workspace/app.py'])
        self.assertEqual(result['tool_choice']['function']['name'],'read_file')

    def test_new_revision_cannot_reuse_reads_from_previous_execution(self):
        body=self.body(read=True)
        body['messages'].append({'role':'user','content':'DELIVERY_TEST_REVISION_V1:/workspace/tests/test_new.py\n'})
        result=apply(body)
        self.assertEqual(result['tool_choice']['function']['name'],'read_file')
        self.assertEqual(result['tools'][0]['function']['parameters']['properties']['path']['enum'],['/workspace/app.py'])

    def body(self, read=False):
        body = {'messages': [{'role': 'user', 'content':
            'DELIVERY_TEST_ARTIFACT_V1:/workspace/tests/test_new.py\n'
            'DELIVERY_TEST_SOURCE_V1:/workspace/app.py\n'}],
            'tools': [{'type': 'function', 'function': {'name': name, 'parameters': {}}}
                      for name in ('read_file', 'write_file', 'terminal')]}
        if read:
            body['messages'] += [{'role': 'assistant', 'tool_calls': [{'id': 'read', 'function': {
                'name': 'read_file', 'arguments': json.dumps({'path': '/workspace/app.py', 'offset': 1, 'limit': 50})}}]},
                {'role': 'tool', 'tool_call_id': 'read', 'content': json.dumps({
                    'content': '1|VALUE = 0', 'total_lines': 1})}]
        return body

    def add_write(self, body, receipt, content='test'):
        body['messages'] += [{'role': 'assistant', 'tool_calls': [{'id': 'write', 'function': {
            'name': 'write_file', 'arguments': json.dumps({'path': '/workspace/tests/test_new.py', 'content': content})}}]},
            {'role': 'tool', 'tool_call_id': 'write', 'content': json.dumps(receipt)}]

    def test_unmarked_requests_unchanged(self):
        body = {'messages': []}
        self.assertIs(apply(body), body)

    def test_real_source_read_precedes_target_bound_write(self):
        body = self.body()
        original = copy.deepcopy(body)
        result = apply(body)
        self.assertEqual(body, original)
        self.assertEqual(result['tool_choice']['function']['name'], 'read_file')
        self.assertTrue(result['tools'][0]['function']['strict'])
        self.assertEqual(result['tools'][0]['function']['parameters']['required'], ['path', 'offset', 'limit'])
        props = result['tools'][0]['function']['parameters']['properties']
        self.assertEqual(props['path']['enum'], ['/workspace/app.py'])
        self.assertEqual(props['limit']['enum'], [50])
        result = apply(self.body(read=True))
        self.assertEqual(result['tool_choice']['function']['name'], 'write_file')
        props = result['tools'][1]['function']['parameters']['properties']
        self.assertEqual(props['path']['enum'], ['/workspace/tests/test_new.py'])
        self.assertEqual(props['content']['minLength'], 1)
        self.assertEqual(props['content']['maxLength'], 6144)
        self.assertIn('ALL unchanged acceptance criteria', result['messages'][-1]['content'])
        self.assertNotIn('parallel_tool_calls', result)
        self.assertTrue(result['provider']['require_parameters'])

    def test_forced_phase_omits_unsupported_parallel_parameter_without_relaxing_schema(self):
        body = self.body(read=True)
        body['parallel_tool_calls'] = False
        result = apply(body)
        self.assertNotIn('parallel_tool_calls', result)
        self.assertTrue(result['provider']['require_parameters'])
        self.assertTrue(result['tools'][1]['function']['strict'])
        self.assertEqual(result['tool_choice']['function']['name'], 'write_file')

    def test_prose_and_failed_or_empty_writes_do_not_open_completion(self):
        for receipt in ({'bytes_written': 4, 'verified': True, 'error': 'denied'},
                        {'bytes_written': 0, 'verified': True},
                        {'bytes_written': 4}, {'bytes_written': 4, 'verified': True, 'path': '/workspace/app.py'}):
            body = self.body(read=True)
            body['messages'].append({'role': 'assistant', 'content': 'I created the test.'})
            self.add_write(body, receipt)
            self.assertEqual(apply(body)['tool_choice']['function']['name'], 'write_file')

    def test_hash_verified_write_receipt_allows_normal_work_not_approval(self):
        body = self.body(read=True)
        content = 'def test_value():\n    assert 0 == 1\n'
        self.add_write(body, {'bytes_written':len(content.encode()), 'verified':True}, content=content)
        self.assertIs(apply(body), body)

    def test_nonempty_write_without_test_methods_cannot_open_normal_work(self):
        for content in ('# Here is the planned suite.\n', 'def test_invalid(:\n'):
            body = self.body(read=True)
            self.add_write(body, {'bytes_written':len(content.encode()), 'verified':True}, content=content)
            self.assertEqual(apply(body)['tool_choice']['function']['name'], 'write_file')

    def test_repeated_write_failure_stops_without_infinite_retries(self):
        body = self.body(read=True)
        self.add_write(body, {'error': 'denied'})
        # Distinct actual call identifiers; duplicate transport records are not retries.
        self.add_write(body, {'error': 'denied'})
        body['messages'][-2]['tool_calls'][0]['id'] = 'write2'
        body['messages'][-1]['tool_call_id'] = 'write2'
        with self.assertRaisesRegex(ValueError, 'failed twice'):
            apply(body)

    def test_bad_path_and_missing_tools_fail_closed(self):
        body = self.body()
        body['messages'][0]['content'] = body['messages'][0]['content'].replace('tests/test_new.py', '../outside/test_new.py')
        with self.assertRaisesRegex(ValueError, 'phase contract'):
            apply(body)
        body = self.body()
        body['tools'] = body['tools'][:1]
        with self.assertRaisesRegex(ValueError, 'existing read and write'):
            apply(body)

    def test_seeded_revision_reads_historic_test_before_edits_not_bootstrap_replacement(self):
        body=self.body(read=True)
        body['messages'][0]['content']+='DELIVERY_TEST_REVISION_V1:/workspace/tests/test_new.py\n'
        result=apply(body)
        self.assertEqual(result['tool_choice']['function']['name'],'read_file')
        self.assertEqual(result['tools'][0]['function']['parameters']['properties']['path']['enum'],['/workspace/tests/test_new.py'])
        body['messages'] += [{'role':'assistant','tool_calls':[{'id':'historic','function':{
            'name':'read_file','arguments':json.dumps({'path':'/workspace/tests/test_new.py','offset':1,'limit':50})}}]},
            {'role':'tool','tool_call_id':'historic','content':json.dumps({'content':'1|def test_historic(): pass','total_lines':1})}]
        result=apply(body)
        self.assertNotIn('tool_choice',result)
        self.assertEqual(result['tools'],body['tools'])
        self.assertIn('Preserve all test methods',result['messages'][-1]['content'])
        self.assertNotIn('FIRST ARTIFACT PHASE',result['messages'][-1]['content'])

    def test_revision_marker_without_exact_declared_artifact_is_rejected(self):
        with self.assertRaises(ValueError):apply({'messages':[{'role':'user','content':'DELIVERY_TEST_REVISION_V1:/workspace/tests/test_new.py\n'}]})
        body=self.body()
        body['messages'][0]['content']+='DELIVERY_TEST_REVISION_V1:/workspace/tests/test_other.py\n'
        with self.assertRaises(ValueError):apply(body)


if __name__ == '__main__':
    unittest.main()
