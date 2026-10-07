import json
import os
import unittest
from unittest.mock import patch
import test_test_artifact_schema as fixtures
from test_artifact_schema import apply
from artifact_response_contract import validate,ArtifactResponseRejected
from surgical_test_edit import typed_schema
from broker import review_tool_policy as policy


class TypedSurgicalTests(unittest.TestCase):
    def test_driver_v3_instruction_does_not_reuse_scaffolding_or_red_protocol(self):
        body=self.body()
        body['messages'][0]['content']=body['messages'][0]['content'].replace('SURGICAL_TEST_V2','SURGICAL_TEST_V3')
        result=apply(body)
        instruction=result['messages'][-1]['content']
        self.assertIn('DRIVER-ONLY MAINTENANCE',instruction)
        self.assertIn('Do not adapt imports',instruction)
        self.assertIn('NOT functional TDD Red',instruction)
        self.assertNotIn('Adapt imports/scaffolding',instruction)
        self.assertNotIn('controller proves Red',instruction)
        self.assertEqual(result['tool_choice']['function']['name'],'surgical_test_edit')
    def test_pinned_acp_toolset_adaptation_is_scoped_and_fail_closed(self):
        from broker.install_review_tool_policy import adapt_acp_toolsets
        anchor='            "read_file", "write_file", "patch", "search_files",\n'
        source='    "coding": {\n'+anchor+'    },\n    "hermes-acp": {\n'+anchor+'        "includes": []\n    },\n'
        adapted=adapt_acp_toolsets(source)
        self.assertEqual(adapted.count('"surgical_test_edit"'),1)
        self.assertNotIn('surgical_test_edit',adapted.split('"hermes-acp"')[0])
        for value in ('',source+source,adapted):
            with self.assertRaises(ValueError):adapt_acp_toolsets(value)
    def test_pinned_default_toolset_adaptation_is_fail_closed(self):
        from broker.install_review_tool_policy import adapt_toolsets
        source='    "read_file", "write_file", "patch", "search_files",\n'
        self.assertIn('"surgical_test_edit"',adapt_toolsets(source))
        for value in ('',source+source,adapt_toolsets(source)):
            with self.assertRaises(ValueError):adapt_toolsets(value)
    def body(self):
        body=fixtures.TestArtifactSchemaTests().surgical_body()
        body['messages'][0]['content']=body['messages'][0]['content'].replace('SURGICAL_TEST_V1','SURGICAL_TEST_V2')
        body['tools'].append({'type':'function','function':typed_schema(self.config())})
        body['messages'] += [{'role':'assistant','tool_calls':[{'id':'read-new','function':{
            'name':'read_file','arguments':json.dumps({'path':self.config()['path'],'offset':1,'limit':50})}}]},
            {'role':'tool','tool_call_id':'read-new','content':json.dumps({'content':'1|source','total_lines':1})}]
        return body

    def config(self):
        return {'path':'/workspace/tests/test_new.py','expected_sha256':'a'*64,'protocol':'typed_v2'}

    def args(self):
        return {'path':self.config()['path'],'expected_sha256':'a'*64,
                'edits':[{'old':'import pytest','new':'import unittest'}]}

    def response(self,args):
        return json.dumps({'choices':[{'message':{'tool_calls':[{'function':{
            'name':'surgical_test_edit','arguments':json.dumps(args)}}]},'finish_reason':'tool_calls'}]}).encode()

    def test_actual_registered_tool_required_and_explicit_schema_selected(self):
        body=self.body();result=apply(body)
        self.assertEqual(result['tool_choice']['function']['name'],'surgical_test_edit')
        chosen=next(t['function'] for t in result['tools'] if t['function']['name']=='surgical_test_edit')
        self.assertEqual(chosen['parameters']['required'],['path','expected_sha256','edits'])
        self.assertNotIn('content',chosen['parameters']['properties'])
        body['tools'].pop()
        with self.assertRaisesRegex(ValueError,'actual registry'):apply(body)

    def test_fixed_rejections_are_distinct_and_no_arguments_disclosed(self):
        body=apply(self.body());validate(body,self.response(self.args()),'application/json')
        for changes,category in [({'path':'/workspace/app.py'},'surgical_path_mismatch'),
                ({'expected_sha256':'b'*64},'surgical_hash_mismatch'),
                ({'edits':[]},'surgical_edits_invalid'),
                ({'content':'PRIVATE'},'surgical_argument_shape_mismatch')]:
            args={**self.args(),**changes}
            with self.assertRaises(ArtifactResponseRejected) as error:validate(body,self.response(args),'application/json')
            self.assertEqual(error.exception.category,category)
            self.assertNotIn('PRIVATE',str(error.exception))

    def test_typed_handler_requires_read_and_denies_legacy_write(self):
        policy.SURGICAL_READ_PAGES.clear()
        with patch.dict(os.environ,{'DELIVERY_EXECUTION_MODE':'implementation',
                'DELIVERY_SURGICAL_TEST_JSON':json.dumps(self.config())}),\
                patch('pathlib.Path.read_text',return_value='one\ntwo\n'),patch('surgical_test_edit.edit_file') as edit:
            edit.side_effect=lambda *a,**kw:{'verified':kw['observed_read']}
            self.assertFalse(json.loads(policy.controlled('surgical_test_edit',self.args()))['verified'])
            policy.observe_surgical_read('read_file',{'path':self.config()['path'],'offset':1,'limit':2},
                json.dumps({'content':'source','total_lines':2}))
            self.assertTrue(json.loads(policy.controlled('surgical_test_edit',self.args()))['verified'])
            for tool in ('write_file','terminal','patch','python'):
                self.assertIn('error',json.loads(policy.controlled(tool,self.args())))
        with patch.dict(os.environ,{'DELIVERY_EXECUTION_MODE':'implementation'},clear=True):
            self.assertIn('error',json.loads(policy.controlled('surgical_test_edit',self.args())))

    def test_receipt_allows_controller_capture_not_another_edit(self):
        body=self.body()
        body['messages'].append({'role':'assistant','tool_calls':[{'id':'edited','function':{
            'name':'surgical_test_edit','arguments':json.dumps(self.args())}}]})
        body['messages'].append({'role':'tool','tool_call_id':'edited','content':json.dumps({
            'operation':'surgical_test_edit_v1','verified':True,'path':self.config()['path'],
            'before_sha256':'a'*64,'sha256':'b'*64,'bytes_written':10,
            'test_bodies_preserved':True,'delivery_approval':False})})
        self.assertIs(apply(body),body)
