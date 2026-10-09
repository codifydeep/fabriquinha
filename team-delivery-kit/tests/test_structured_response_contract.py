import copy
import json
import unittest
from unittest.mock import patch
import test_read_stream_recovery as fixtures
import model_proxy as proxy
from structured_response_contract import validate,StructuredResponseRejected


class StructuredResponseTests(unittest.TestCase):
    def setUp(self):
        self.body={'response_format':{'type':'json_schema','json_schema':{'schema':{
            'type':'object','properties':{'action':{'enum':['request_test_revision']},
                'reason':{'type':'string','minLength':1,'maxLength':20},
                'optional_files':{'type':'array','maxItems':0}},
            'required':['action','reason','optional_files'],'additionalProperties':False}}}}
        self.decision={'action':'request_test_revision','reason':'Add controls','optional_files':[]}

    def wire(self,text,finish='stop'):
        return json.dumps({'choices':[{'message':{'content':text},'finish_reason':finish}]}).encode()

    def test_valid_actual_json_passes_unchanged(self):
        raw=self.wire(json.dumps(self.decision));before=bytes(raw)
        self.assertIsNone(validate(self.body,raw,'application/json'))
        self.assertEqual(raw,before)

    def test_schema_diagnostic_contains_only_constraints_and_digest(self):
        import hashlib
        secret='PRIVATE_REJECTED_VALUE'
        raw=self.wire(json.dumps({**self.decision,'reason':secret*3,secret:secret}))
        with self.assertRaises(StructuredResponseRejected) as caught:
            validate(self.body,raw,'application/json')
        diagnostic=caught.exception.diagnostic
        self.assertEqual(diagnostic,{'version':'structured-constraint-v1',
            'constraints':['additionalProperties','maxLength'],
            'upstream_sha256':hashlib.sha256(raw).hexdigest()})
        self.assertNotIn(secret,json.dumps(diagnostic))
        self.assertNotIn(secret,str(caught.exception))

    def test_non_json_rejection_does_not_expose_content(self):
        with self.assertRaises(StructuredResponseRejected) as caught:
            validate(self.body,self.wire('PRIVATE_TEXT'),'application/json')
        self.assertIsNone(caught.exception.diagnostic)

    def test_prose_fence_duplicate_keys_extra_fields_and_long_reason_rejected(self):
        raw=json.dumps(self.decision)
        for text in ['Preamble '+raw,'```json\n'+raw+'\n```',raw+' trailing',
            raw.replace('"reason":','"reason":"first","reason":'),
            json.dumps({**self.decision,'reason':'x'*21}),json.dumps({**self.decision,'override':True}),
            json.dumps({**self.decision,'optional_files':['tests/old.py']})]:
            with self.assertRaises(StructuredResponseRejected):validate(self.body,self.wire(text),'application/json')

    def test_tool_phase_is_separate_and_nonterminal_answer_is_rejected(self):
        self.assertIsNone(validate({**self.body,'tool_choice':{'type':'function','function':{'name':'read_file'}}},b'not decision','application/json'))
        with self.assertRaises(StructuredResponseRejected):validate(self.body,self.wire(json.dumps(self.decision),'length'),'application/json')

    def test_actual_stream_assembled_before_forwarding(self):
        text=json.dumps(self.decision)
        frames=[{'choices':[{'index':0,'delta':{'content':text[:20]},'finish_reason':None}]},
            {'choices':[{'index':0,'delta':{'content':text[20:]},'finish_reason':None}]},
            {'choices':[{'index':0,'delta':{},'finish_reason':'stop'}]}]
        raw=(''.join('data: '+json.dumps(f)+'\n\n' for f in frames)+'data: [DONE]\n\n').encode()
        self.assertIsNone(validate(self.body,raw,'text/event-stream'))
        with self.assertRaises(StructuredResponseRejected):validate(self.body,raw.replace(b'data: [DONE]',b''),'text/event-stream')

    def test_single_empty_repeated_stop_trailer_preserves_exact_decision(self):
        def frame(delta,finish):
            return 'data: '+json.dumps({'choices':[{'index':0,'delta':delta,
                'finish_reason':finish}]})+'\n\n'
        prefix=frame({'content':json.dumps(self.decision)},None)+frame({},'stop')
        trailer=frame({'content':'','role':'assistant'},'stop')
        raw=(prefix+trailer+'data: [DONE]\n\n').encode()
        validate(self.body,raw,'text/event-stream')
        for late in (frame({'content':'PRIVATE_NEW_CONTENT'},'stop'),
                     frame({'role':'user'},'stop'),
                     frame({},'length'),trailer+trailer,
                     frame({'tool_calls':[{'id':'unexpected'}]},'stop')):
            with self.assertRaises(StructuredResponseRejected):
                validate(self.body,(prefix+late+'data: [DONE]\n\n').encode(),'text/event-stream')
        with self.assertRaises(StructuredResponseRejected):
            validate(self.body,(prefix+trailer).encode(),'text/event-stream')

    def test_empty_usage_trailer_cannot_make_invalid_json_or_schema_valid(self):
        for text in ('PRIVATE_TEXT',json.dumps({**self.decision,'override':True})):
            frames=[{'choices':[{'index':0,'delta':{'content':text},'finish_reason':None}]},
                    {'choices':[{'index':0,'delta':{},'finish_reason':'stop'}]},
                    {'choices':[{'index':0,'delta':{'content':''},'finish_reason':'stop'}]}]
            raw=(''.join('data: '+json.dumps(f)+'\n\n' for f in frames)+'data: [DONE]\n\n').encode()
            with self.assertRaises(StructuredResponseRejected):validate(self.body,raw,'text/event-stream')

    def test_proxy_rejects_response_before_forwarding_without_identical_retry(self):
        fixture=fixtures.ReadStreamRecoveryTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        body=fixtures.request_body();body['messages'][0]['content']='DELIVERY_STRUCTURED_DECISION_V1:technical\n'
        upstream=self.wire('PRIVATE_PROVIDER_ERROR prose instead of JSON')
        with patch.object(proxy,'forward',return_value=(200,upstream,'application/json')) as forward:
            reply=fixture.request(body)
        self.assertEqual(reply.status,502)
        self.assertEqual(json.loads(reply.wfile.getvalue()),{'error':{'code':'structured_decision_response_invalid'}})
        forward.assert_called_once()
        self.assertEqual(proxy.load_calls(),1)

    def test_proxy_accepts_complete_valid_decision_without_modifying_bytes(self):
        fixture=fixtures.ReadStreamRecoveryTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        body=fixtures.request_body();body['messages'][0]['content']='DELIVERY_STRUCTURED_DECISION_V1:technical\n'
        upstream=self.wire(json.dumps(self.decision))
        with patch.object(proxy,'forward',return_value=(200,upstream,'application/json')):
            reply=fixture.request(body)
        self.assertEqual(reply.status,200)
        self.assertEqual(reply.wfile.getvalue(),upstream)
