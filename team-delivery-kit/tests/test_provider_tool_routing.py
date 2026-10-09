import copy
import unittest
from provider_tool_routing import wire


class ProviderToolRoutingTests(unittest.TestCase):
    def qa_body(self):
        import json
        from decision_schema import apply
        path='/evidence/previous/qa.json'
        body=apply({'model':'anthropic/claude-haiku-5.5','messages':[
            {'role':'user','content':'DELIVERY_STRUCTURED_DECISION_V1:qa\nDELIVERY_REVIEW_READ_PATH:'+path+'\n'},
            {'role':'assistant','tool_calls':[{'id':'r','function':{'name':'read_file',
                'arguments':json.dumps({'path':path})}}]},
            {'role':'tool','tool_call_id':'r','content':json.dumps({'content':'1|{}\n','total_lines':1})}],
            'tools':[{'function':{'name':'unused'}}]})
        return body

    def test_qa_wire_projection_preserves_canonical_contract_and_requires_reads(self):
        body=self.qa_body(); before=copy.deepcopy(body)
        result=wire(body)
        self.assertEqual(body,before)
        self.assertNotIn('anyOf',result['response_format']['json_schema']['schema'])
        self.assertIn('anyOf',body['response_format']['json_schema']['schema'])
        self.assertNotIn('tools',result)
        self.assertEqual(result['provider'],body['provider'])
        self.assertEqual(result['messages'],body['messages'])
        self.assertTrue(result['response_format']['json_schema']['strict'])
        self.assertEqual(result['response_format']['json_schema']['schema']['properties'],
                         body['response_format']['json_schema']['schema']['properties'])

    def test_qa_projection_cannot_omit_canonical_branch_constraints(self):
        body=self.qa_body()
        body['response_format']['json_schema']['schema']['anyOf'][0]['properties']['acceptance']['maxItems']=5
        with self.assertRaisesRegex(ValueError,'branch constraints'): wire(body)
        body=self.qa_body();body['tool_choice']='auto'
        with self.assertRaisesRegex(ValueError,'canonical QA'): wire(body)

    def test_projected_qa_response_still_rejects_inconsistent_decisions_locally(self):
        import json
        from structured_response_contract import validate,StructuredResponseRejected
        body=self.qa_body(); wire(body)
        def response(decision):
            return json.dumps({'choices':[{'finish_reason':'stop',
                'message':{'content':json.dumps(decision)}}]}).encode()
        valid={'decision':'blocked','root_cause':'Scenario selects a nonexistent option.',
               'editable_code_files':[],'new_test_file':'','acceptance':[]}
        validate(body,response(valid),'application/json')
        for invalid in ({**valid,'editable_code_files':['app/static/app.js']},
                        {**valid,'new_test_file':'tests/imagined.py'},
                        {**valid,'decision':'repair'},
                        {**valid,'release_homologated':True}):
            with self.assertRaises(StructuredResponseRejected):
                validate(body,response(invalid),'application/json')

    def body(self):
        return {'model':'anthropic/claude-haiku-5.5','provider':{'require_parameters':True},
            'tool_choice':{'type':'function','function':{'name':'selected'}},
            'tools':[{'type':'function','function':{'name':'selected','strict':True,
                'parameters':{'type':'object','properties':{'value':{'type':'string','maxLength':20}},
                              'required':['value'],'additionalProperties':False}}}],
            'messages':[{'role':'user','content':'Original instruction'}],'max_tokens':128}

    def test_only_routing_hint_changes_not_schema_or_authority(self):
        body=self.body();before=copy.deepcopy(body)
        result=wire(body)
        self.assertEqual(body,before)
        self.assertIs(result['provider']['require_parameters'],False)
        expected=copy.deepcopy(before);expected['provider']['require_parameters']=False
        self.assertEqual(result,expected)
        self.assertTrue(result['tools'][0]['function']['strict'])

    def test_other_models_and_text_planning_are_untouched(self):
        for change in ({'model':'another/model'},{'tool_choice':'none'},{'tool_choice':'auto'}):
            body={**self.body(),**change}
            self.assertEqual(wire(body),body)

    def test_unknown_or_duplicate_selected_tool_fails_closed(self):
        body=self.body();body['tools']=[]
        with self.assertRaises(ValueError):wire(body)
        body=self.body();body['tools']*=2
        with self.assertRaises(ValueError):wire(body)

    def test_review_projection_does_not_mutate_canonical_union_constraints(self):
        body=self.body();body['tool_choice']['function']['name']='submit_test_review'
        function=body['tools'][0]['function'];function['name']='submit_test_review'
        properties={'action':{'type':'string','enum':['approve_test_revision','reject_test_revision']},
            'reason':{'type':'string','maxLength':1200},'optional_files':{'type':'array','maxItems':0},
            'manifest_sha256':{'type':'string','enum':['a'*64]},
            'findings':{'type':'array','items':{'type':'object','anyOf':[{'properties':{'line':{'enum':[3]}}}]}}}
        function['parameters']={'type':'object','properties':properties,'anyOf':[{'type':'object'}]}
        before=copy.deepcopy(body);result=wire(body)
        self.assertEqual(body,before)
        schema=result['tools'][0]['function']['parameters']
        self.assertNotIn('anyOf',schema)
        self.assertNotIn('anyOf',schema['properties']['findings']['items'])
        self.assertEqual(schema['properties']['manifest_sha256'],properties['manifest_sha256'])
        self.assertTrue(result['tools'][0]['function']['strict'])
        self.assertEqual(result['messages'],body['messages'])

    def test_unrecognized_review_schema_cannot_project(self):
        body=self.body();body['tool_choice']['function']['name']='submit_test_review'
        body['tools'][0]['function']['name']='submit_test_review'
        body['tools'][0]['function']['parameters']['anyOf']=[{}]
        with self.assertRaises(ValueError):wire(body)
