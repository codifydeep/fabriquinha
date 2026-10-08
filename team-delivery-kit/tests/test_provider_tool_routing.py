import copy
import unittest
from provider_tool_routing import wire


class ProviderToolRoutingTests(unittest.TestCase):
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
