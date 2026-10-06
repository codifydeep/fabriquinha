import json
import unittest
from artifact_response_contract import validate,metrics,ArtifactResponseRejected
from test_artifact_schema import apply


class ArtifactResponseTests(unittest.TestCase):
    def test_encoded_suite_is_diagnosed_not_decoded_or_executed(self):
        from test_test_artifact_schema import TestArtifactSchemaTests
        body=apply(TestArtifactSchemaTests().body(read=True))
        suite='import unittest\nclass Example(unittest.TestCase):\n def test_x(self): self.assertEqual(1,2)\n'
        content=repr(suite)
        call={'function':{'name':'write_file','arguments':json.dumps(dict(path='/workspace/tests/test_new.py',content=content))}}
        with self.assertRaises(ArtifactResponseRejected) as raised:validate(body,self.response(call),'application/json')
        info=raised.exception.diagnostic
        self.assertEqual(info['test_methods'],0);self.assertTrue(info['top_level_string_only'])
        self.assertEqual(info['embedded_test_methods'],1)
        self.assertNotIn(suite,json.dumps(info))

    def test_helper_only_structure_is_distinct_from_encoded_suite(self):
        from artifact_response_contract import python_structure
        import ast
        content='def helper(): return 1\n'
        info=python_structure(content,ast.parse(content))
        self.assertFalse(info['top_level_string_only']);self.assertEqual(info['functions'],1)
        self.assertEqual(info['embedded_test_methods'],0)

    def test_literal_newlines_in_comment_cannot_pass_as_test_source(self):
        from test_test_artifact_schema import TestArtifactSchemaTests
        body=apply(TestArtifactSchemaTests().body(read=True))
        content='# suite\\nimport unittest\\nclass T(unittest.TestCase):\\n def test_x(self): assert False\\n'
        call={'function':{'name':'write_file','arguments':json.dumps(dict(path='/workspace/tests/test_new.py',content=content))}}
        with self.assertRaises(ArtifactResponseRejected) as raised:validate(body,self.response(call),'application/json')
        info=raised.exception.diagnostic
        self.assertEqual(info['physical_newlines'],0);self.assertEqual(info['escaped_newlines'],4)
        self.assertEqual(info['test_methods'],0)
    def test_surgical_response_accepts_only_bound_edit_envelope(self):
        from test_test_artifact_schema import TestArtifactSchemaTests
        body=TestArtifactSchemaTests().surgical_body()
        body['messages'] += [{'role':'assistant','tool_calls':[{'id':'target-read','function':{
            'name':'read_file','arguments':json.dumps({'path':'/workspace/tests/test_new.py','offset':1,'limit':50})}}]},
            {'role':'tool','tool_call_id':'target-read','content':json.dumps({'content':'1|test source','total_lines':1})}]
        body=apply(body)
        envelope={'expected_sha256':'a'*64,'edits':[{'old':'import pytest','new':'import unittest'}]}
        for content,valid in ((json.dumps(envelope),True),('def test_x(): assert True',False),
                             (json.dumps({**envelope,'expected_sha256':'b'*64}),False)):
            call={'function':{'name':'write_file','arguments':json.dumps({'path':'/workspace/tests/test_new.py','content':content})}}
            if valid:validate(body,self.response(call),'application/json')
            else:
                with self.assertRaises(ArtifactResponseRejected):validate(body,self.response(call),'application/json')

    def setUp(self):
        self.body=apply({'messages':[{'role':'user','content':
            'DELIVERY_TEST_ARTIFACT_V1:/workspace/tests/test_new.py\nDELIVERY_TEST_SOURCE_V1:/workspace/app.py\n'}],
            'tools':[{'type':'function','function':{'name':n,'parameters':{}}} for n in ('read_file','write_file')]})
        self.call={'function':{'name':'read_file','arguments':json.dumps(dict(path='/workspace/app.py',offset=1,limit=50))}}

    def response(self,call=None,finish='tool_calls'):
        return json.dumps({'choices':[{'message':{'tool_calls':[call or self.call]},'finish_reason':finish}]}).encode()

    def test_valid_json_and_streamed_arguments(self):
        validate(self.body,self.response(),'application/json')
        name={'choices':[{'index':0,'delta':{'tool_calls':[{'index':0,'function':{'name':'read_file','arguments':''}}]}}]}
        args={'choices':[{'index':0,'delta':{'tool_calls':[{'index':0,'function':{'arguments':self.call['function']['arguments']}}]},'finish_reason':'tool_calls'}]}
        stream='\n'.join('data: '+json.dumps(x) for x in (name,args))+'\ndata: [DONE]\n'
        validate(self.body,stream.encode(),'text/event-stream')
        with self.assertRaisesRegex(ValueError,'artifact tool response invalid'):
            validate(self.body,stream.replace('data: [DONE]','').encode(),'text/event-stream')

    def test_prose_wrong_tool_path_or_page_are_rejected(self):
        for data in (self.response(finish='stop'),b'{"choices":[{"message":{"content":"done"},"finish_reason":"stop"}]}',
            self.response({'function':{'name':'terminal','arguments':'{}'}}),
            self.response({'function':{'name':'read_file','arguments':json.dumps(dict(path='/workspace/other.py',offset=1,limit=50))}})):
            with self.assertRaisesRegex(ValueError,'artifact tool response invalid'):
                validate(self.body,data,'application/json')

    def test_nonartifact_decisions_unaffected_and_metadata_has_no_paths(self):
        validate({'messages':[]},b'private text','application/json')
        self.assertEqual(metrics(self.body),{'artifact_contract_present':True,'artifact_selected_tool':'read_file'})

    def test_rejection_category_is_allowlisted_without_provider_text(self):
        with self.assertRaises(ArtifactResponseRejected) as raised:
            validate(self.body, b'private provider text', 'application/json')
        self.assertEqual(raised.exception.category, 'invalid_response_encoding')
        self.assertEqual(str(raised.exception), 'artifact tool response invalid')
        with self.assertRaises(ArtifactResponseRejected) as raised:
            validate(self.body, self.response({'function':{'name':'terminal','arguments':'{}'}}), 'application/json')
        self.assertEqual(raised.exception.category, 'wrong_selected_tool')

    def test_inner_invalid_json_is_distinct_from_invalid_stream_encoding(self):
        with self.assertRaises(ArtifactResponseRejected) as raised:
            validate(self.body,self.response({'function':{'name':'read_file','arguments':'{"path":'}}),'application/json')
        self.assertEqual(raised.exception.category,'invalid_tool_argument_json')

    def test_first_write_maximum_is_enforced_not_just_advertised(self):
        from test_test_artifact_schema import TestArtifactSchemaTests
        body=apply(TestArtifactSchemaTests().body(read=True))
        for size in (6144,6145):
            prefix='def test_value():\n    assert False\n#'
            content=prefix+'x'*(size-len(prefix))
            data=self.response({'function':{'name':'write_file','arguments':json.dumps({'path':'/workspace/tests/test_new.py','content':content})}})
            if size==6144:validate(body,data,'application/json')
            else:
                with self.assertRaises(ArtifactResponseRejected):validate(body,data,'application/json')

    def test_python_first_write_requires_valid_syntax_and_actual_test_method(self):
        from test_test_artifact_schema import TestArtifactSchemaTests
        body=apply(TestArtifactSchemaTests().body(read=True))
        for content,category in [('def helper():\n    return 1\n','artifact_test_methods_missing'),
                                 ('def test_value(:','artifact_test_syntax_invalid')]:
            data=self.response({'function':{'name':'write_file','arguments':json.dumps(
                {'path':'/workspace/tests/test_new.py','content':content})}})
            with self.assertRaises(ArtifactResponseRejected) as raised:validate(body,data,'application/json')
            self.assertEqual(raised.exception.category,category)

    def test_structured_diagnostic_forced_read_rejects_missing_or_wrong_arguments(self):
        from decision_schema import apply as decision
        body=decision({'messages':[{'role':'user','content':'DELIVERY_STRUCTURED_DECISION_V1:technical\n'
            'DELIVERY_REVIEW_READ_PATH:/evidence/candidate/test.py\n'}],
            'tools':[{'function':{'name':'read_file'}}]})
        self.assertTrue(body['tools'][0]['function']['strict'])
        args={'path':'/evidence/candidate/test.py','offset':1,'limit':100}
        good={'function':{'name':'read_file','arguments':json.dumps(args)}}
        validate(body,self.response(good),'application/json')
        for bad in ({},dict(args,path='/workspace/other.py')):
            with self.assertRaises(ArtifactResponseRejected):
                validate(body,self.response({'function':{'name':'read_file','arguments':json.dumps(bad)}}),'application/json')
