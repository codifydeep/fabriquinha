import copy
import json
import unittest
from decision_schema import apply as schema
import typed_decision_contract as typed
from structured_response_contract import StructuredResponseRejected


class TypedDeploymentEvidenceTests(unittest.TestCase):
    def body(self):
        return typed.apply(schema({'messages':[{'role':'user','content':
            'DELIVERY_DEPLOYMENT_EVIDENCE_V1:'+'a'*64+'\nDELIVERY_TYPED_DEPLOYMENT_EVIDENCE_V1:'+'a'*64}], 'tools':[]}))

    def decision(self):
        return dict(decision='ACCEPT_EVIDENCE',evidence_sha256='a'*64,reason='Evidence is consistent.',
            limitations=['Assessment only, no independent test execution.'],release_homologated=False,
            product_admission_authorized=False,historical_tdd_red=False)

    def wire(self,value,name='submit_deployment_evidence'):
        return json.dumps({'choices':[{'index':0,'finish_reason':'tool_calls','message':{'content':None,
            'tool_calls':[{'type':'function','function':{'name':name,'arguments':json.dumps(value)}}]}}]}).encode()

    def test_actual_typed_arguments_preserved_without_worker_execution(self):
        body=self.body();self.assertNotIn('response_format',body)
        self.assertEqual(body['tool_choice']['function']['name'],'submit_deployment_evidence')
        out,_,receipt=typed.translate(body,self.wire(self.decision()),'application/json')
        self.assertEqual(json.loads(json.loads(out)['choices'][0]['message']['content']),self.decision())
        self.assertFalse(receipt['worker_tool_executed']);self.assertFalse(receipt['delivery_approval'])

    def test_wrong_digest_authority_overlong_reason_and_wrong_tool_rejected(self):
        for key,value in [('evidence_sha256','b'*64),('release_homologated',True),('reason','x'*1201)]:
            bad=dict(self.decision(),**{key:value})
            with self.assertRaises(StructuredResponseRejected):typed.translate(self.body(),self.wire(bad),'application/json')
        with self.assertRaises(StructuredResponseRejected):typed.translate(self.body(),self.wire(self.decision(),'terminal'),'application/json')

    def test_marker_conflicts_rejected_and_plain_schema_unchanged(self):
        raw={'messages':[{'role':'user','content':'DELIVERY_DEPLOYMENT_EVIDENCE_V1:'+'a'*64}],'tools':[]}
        self.assertIn('response_format',typed.apply(schema(copy.deepcopy(raw))))
        raw['messages'][0]['content']+='\nDELIVERY_TYPED_DEPLOYMENT_EVIDENCE_V1:'+'b'*64
        with self.assertRaises(ValueError):typed.apply(schema(raw))

    def test_stream_preserves_values_and_rejects_prose(self):
        frame={'choices':[{'index':0,'delta':{'tool_calls':[{'index':0,'type':'function','function':{
            'name':'submit_deployment_evidence','arguments':json.dumps(self.decision())}}]},'finish_reason':'tool_calls'}]}
        raw=('data: '+json.dumps(frame)+'\n\ndata: [DONE]\n').encode()
        out,_,proof=typed.translate(self.body(),raw,'text/event-stream')
        self.assertIn(b'ACCEPT_EVIDENCE',out);self.assertFalse(proof['worker_tool_executed'])
        frame['choices'][0]['delta']['content']='I approve'
        with self.assertRaises(StructuredResponseRejected):typed.translate(self.body(),('data: '+json.dumps(frame)+'\n\ndata: [DONE]\n').encode(),'text/event-stream')

    def test_bounded_ascii_padding_only_preserves_arguments(self):
        body=self.body();frame=json.loads(self.wire(self.decision()));frame['choices'][0]['message']['content']=' '
        raw=json.dumps(frame).encode();out,receipt=typed.normalize_evidence_padding(body,raw,'application/json')
        typed.translate(body,out,'application/json');self.assertEqual(receipt['padding_chars'],1)
        self.assertTrue(receipt['model_arguments_unchanged'])
        frame['choices'][0]['message']['content']='approved'
        raw=json.dumps(frame).encode();out,receipt=typed.normalize_evidence_padding(body,raw,'application/json')
        self.assertEqual(out,raw);self.assertIsNone(receipt)
