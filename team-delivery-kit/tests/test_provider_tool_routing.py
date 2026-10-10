import copy
import unittest
from provider_tool_routing import wire


class ProviderToolRoutingTests(unittest.TestCase):
    def mediation_body(self):
        from test_typed_decision_contract import TypedDecisionTests
        from decision_schema import apply
        from typed_decision_contract import apply as typed
        body=TypedDecisionTests().review_body(findings=True,observed=True)
        messages=copy.deepcopy(body['messages'])
        messages[0]['content']=messages[0]['content'].replace(
            'DELIVERY_STRUCTURED_DECISION_V1:test_review:'+'a'*64,
            'DELIVERY_STRUCTURED_DECISION_V1:technical').replace(
            'DELIVERY_TYPED_REVIEW_V1:'+'a'*64,
            'DELIVERY_TYPED_DECISION_V1\nDELIVERY_TYPED_TEST_DIAGNOSIS_V1\nDELIVERY_REVIEW_RECONSIDERATION_V1')
        return typed(apply({'model':'anthropic/claude-haiku-5.5','messages':messages}))

    def test_mediation_wire_projection_keeps_canonical_validation_and_decision_authority(self):
        import json
        from typed_decision_contract import translate
        from structured_response_contract import StructuredResponseRejected
        body=self.mediation_body();before=copy.deepcopy(body);projected=wire(body)
        self.assertEqual(body,before)
        schema=projected['tools'][0]['function']['parameters']
        self.assertNotIn('anyOf',json.dumps(schema))
        original=body['tools'][0]['function']['parameters']
        for field in ('action','reason','optional_files'):
            self.assertEqual(schema['properties'][field],original['properties'][field])
        self.assertEqual(schema['properties']['findings']['items']['properties'],
                         original['properties']['findings']['items']['properties'])
        self.assertEqual(schema['required'],original['required'])
        self.assertFalse(schema['additionalProperties'])
        self.assertEqual(projected['messages'][:-1],body['messages'])
        self.assertIn('PROVIDER_UNION_CONSTRAINTS_V1',projected['messages'][-1]['content'])
        self.assertTrue(projected['tools'][0]['function']['strict'])
        self.assertEqual(schema['properties']['action'],body['tools'][0]['function']['parameters']['properties']['action'])
        from test_typed_decision_contract import TypedDecisionTests
        decision=dict(action='request_review_reconsideration',reason='The check exists',optional_files=[],
            findings=[dict(kind='review_disagreement',tree='candidate',path='tests/test_new.py',
                test='__module__',line=1,quote='assert value',expected='Retain check',observed='Retained')])
        _,_,receipt=translate(body,TypedDecisionTests().wire(decision),'application/json')
        self.assertFalse(receipt['delivery_approval']);self.assertFalse(receipt['worker_tool_executed'])
        for invalid in ({**decision,'action':'approve_test_revision'}, {**decision,'findings':[]},
                        {**decision,'findings':[{**decision['findings'][0],'quote':'invented evidence'}]},
                        {**decision,'action':'request_test_revision'}):
            with self.assertRaises(StructuredResponseRejected):
                translate(body,TypedDecisionTests().wire(invalid),'application/json')

    def test_mediation_projection_rejects_forged_schema_or_missing_observed_reads(self):
        for change in ('schema','strict','read'):
            body=self.mediation_body()
            if change=='schema':body['tools'][0]['function']['parameters']['anyOf']=[]
            if change=='strict':body['tools'][0]['function']['strict']=False
            if change=='read':body['messages']=[body['messages'][0]]
            with self.assertRaises(ValueError):wire(body)

    def test_proxy_uses_projected_wire_but_rejects_forged_mediation_locally(self):
        import json
        import io
        from pathlib import Path
        from unittest.mock import patch,MagicMock
        import model_proxy as proxy
        from test_read_stream_recovery import ReadStreamRecoveryTests,request_body
        from test_typed_decision_contract import TypedDecisionTests
        f=ReadStreamRecoveryTests();f.setUp();self.addCleanup(f.doCleanups)
        incoming=request_body();incoming['model']='anthropic/claude-haiku-5.5'
        incoming['messages']=self.mediation_body()['messages']
        valid=dict(action='request_review_reconsideration',reason='The check exists',optional_files=[],
            findings=[dict(kind='review_disagreement',tree='candidate',path='tests/test_new.py',
                test='__module__',line=1,quote='assert value',expected='Retain check',observed='Retained')])
        for decision,status in ((valid,200),({**valid,'action':'approve_test_revision'},502)):
            response=io.BytesIO(TypedDecisionTests().wire(decision));response.status=200
            response.getheader=lambda *_:'application/json'
            connection=MagicMock();connection.getresponse.return_value=response
            original_read=Path.read_text
            def read_text(path,*args,**kwargs):
                return 'synthetic-credential-not-real' if str(path)=='/secret/openrouter.key' else original_read(path,*args,**kwargs)
            with patch.object(proxy,'MODEL','anthropic/claude-haiku-5.5'), \
                    patch.object(proxy.http.client,'HTTPSConnection',return_value=connection), \
                    patch.object(Path,'read_text',read_text):
                result=f.request(incoming)
            self.assertEqual(result.status,status)
            connection.request.assert_called_once()
            transmitted=json.loads(connection.request.call_args.args[2])
            self.assertNotIn('anyOf',json.dumps(transmitted['tools']))
            self.assertEqual(transmitted['tool_choice']['function']['name'],'submit_delivery_decision')
            hints=json.loads(transmitted['messages'][-1]['content'].split('\n',2)[2])
            self.assertTrue(hints['locations'])
            self.assertFalse(hints['verdict_accepted'])
            if status==200:
                output=json.loads(result.wfile.getvalue())
                self.assertEqual(json.loads(output['choices'][0]['message']['content'])['action'],valid['action'])

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
        import json
        from test_typed_decision_contract import TypedDecisionTests
        body=TypedDecisionTests().review_body(findings=True,observed=True)
        body['model']='anthropic/claude-haiku-5.5'
        properties=body['tools'][0]['function']['parameters']['properties']
        before=copy.deepcopy(body);result=wire(body)
        self.assertEqual(body,before)
        schema=result['tools'][0]['function']['parameters']
        self.assertNotIn('anyOf',schema)
        self.assertNotIn('anyOf',schema['properties']['findings']['items'])
        self.assertEqual(schema['properties']['manifest_sha256'],properties['manifest_sha256'])
        self.assertTrue(result['tools'][0]['function']['strict'])
        self.assertEqual(result['messages'][:-1],body['messages'])
        hints=json.loads(result['messages'][-1]['content'].split('\n',2)[2])
        self.assertEqual(hints['locations'],properties['findings']['items']['anyOf'])
        self.assertEqual(hints['actions'][0]['action'],['approve_test_revision'])
        self.assertEqual(hints['actions'][0]['maxItems'],0)
        self.assertEqual(hints['actions'][1]['minItems'],1)
        self.assertFalse(hints['verdict_accepted'])

    def test_review_projection_rejects_forged_union_even_with_matching_fields(self):
        from test_typed_decision_contract import TypedDecisionTests
        body=TypedDecisionTests().review_body(findings=True,observed=True)
        body['model']='anthropic/claude-haiku-5.5'
        body['tools'][0]['function']['parameters']['anyOf'][0]['properties']['findings']['maxItems']=3
        with self.assertRaises(ValueError):wire(body)

    def test_explained_locations_never_accept_invalid_approval_or_fabricated_quote(self):
        from test_typed_decision_contract import TypedDecisionTests
        from typed_decision_contract import translate
        from structured_response_contract import StructuredResponseRejected
        fixture=TypedDecisionTests();body=fixture.review_body(findings=True,observed=True)
        body['model']='anthropic/claude-haiku-5.5';wire(body)
        finding=dict(kind='missing_coverage',tree='candidate',path='tests/test_new.py',test='__module__',
            line=1,quote='assert value',expected='Check behavior',observed='Missing condition')
        base=dict(action='reject_test_revision',reason='Missing case',optional_files=[],
            manifest_sha256='a'*64,findings=[finding])
        for invalid in ({**base,'action':'approve_test_revision'},
                        {**base,'findings':[{**finding,'quote':'fabricated'}]},
                        {**base,'findings':[]}):
            with self.assertRaises(StructuredResponseRejected):
                translate(body,fixture.wire(invalid),'application/json')

    def test_unrecognized_review_schema_cannot_project(self):
        body=self.body();body['tool_choice']['function']['name']='submit_test_review'
        body['tools'][0]['function']['name']='submit_test_review'
        body['tools'][0]['function']['parameters']['anyOf']=[{}]
        with self.assertRaises(ValueError):wire(body)
