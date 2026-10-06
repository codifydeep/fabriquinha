import json
import unittest
from decision_schema import apply as decision_schema
from typed_decision_contract import apply, translate, NAME


class TypedDecompositionContractTests(unittest.TestCase):
    def body(self):
        return decision_schema({'messages':[{'role':'user','content':
            'DELIVERY_TYPED_DECOMPOSITION_V1\nDELIVERY_TEST_DECOMPOSITION_V1\n'
            'DELIVERY_STRUCTURED_DECISION_V1:technical\n'
            'DELIVERY_DECOMPOSITION_CRITERION:C01\nDELIVERY_DECOMPOSITION_CRITERION:C02\n'}]})

    def test_non_executing_typed_proposal_preserves_exact_arguments(self):
        body=apply(self.body())
        self.assertEqual(body['tool_choice']['function']['name'],NAME)
        proposal=dict(action='propose_test_decomposition',reason='Two experiments.',optional_files=[],units=[
            dict(id='U1',depends_on=[],criteria=['C01'],objective='Clearing control.'),
            dict(id='U2',depends_on=['U1'],criteria=['C02'],objective='Stale paint control.')])
        data=json.dumps({'choices':[{'finish_reason':'tool_calls','message':{'content':None,
            'tool_calls':[{'id':'c','type':'function','function':{'name':NAME,'arguments':json.dumps(proposal)}}]}}]}).encode()
        translated,media,receipt=translate(body,data,'application/json')
        self.assertEqual(json.loads(json.loads(translated)['choices'][0]['message']['content']),proposal)
        self.assertEqual(media,'application/json')
        self.assertIsNotNone(receipt)

    def test_no_raw_json_or_prose_recovery(self):
        from structured_response_contract import StructuredResponseRejected
        body=apply(self.body())
        raw=json.dumps({'choices':[{'finish_reason':'stop','message':{'content':'Here is the proposal'}}]}).encode()
        with self.assertRaises(StructuredResponseRejected):translate(body,raw,'application/json')

    def test_does_not_accept_review_execution_or_unknown_fields(self):
        for mutation in ('action','fields','conflict'):
            b=self.body()
            if mutation=='action':b['response_format']['json_schema']['schema']['properties']['action']['enum']=['approve_test_revision']
            if mutation=='fields':b['response_format']['json_schema']['schema']['properties']['execute']={'type':'boolean'}
            if mutation=='conflict':b['messages'][0]['content']+='DELIVERY_TYPED_DECISION_V1\n'
            with self.assertRaises(ValueError):apply(b)

    def test_inspection_is_not_replaced_by_submission(self):
        b={'messages':[{'role':'user','content':'DELIVERY_TYPED_DECOMPOSITION_V1\n'}],
            'tool_choice':{'type':'function','function':{'name':'read_file'}}}
        self.assertIs(apply(b),b)
