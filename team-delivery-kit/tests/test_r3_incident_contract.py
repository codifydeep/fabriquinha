import json
import unittest
from jsonschema import Draft202012Validator
from decision_schema import apply as decision_schema
from typed_decision_contract import apply as typed,translate
from structured_response_contract import StructuredResponseRejected
from r3_incident_contract import schema,request_contract,NAME


class R3IncidentContractTests(unittest.TestCase):
    def body(self,kind='diagnose',proposal=None):
        note='DELIVERY_R3_INCIDENT_V1:'+kind+':'+'a'*64+'\nDELIVERY_R3_FACT:F01\nDELIVERY_R3_FACT:F02'
        if proposal:note+='\nDELIVERY_R3_PROPOSAL_V1:'+proposal
        return {'messages':[{'role':'user','content':note}],'tools':[]}

    def decision(self):
        return dict(action='request_experiment',evidence_sha256='a'*64,reason='F01: controller handle missing; inspect existing receipts.',
            fact_ids=['F01','F02'],experiment='verify_frozen_delivery',execution_authorized=False,release_homologated=False)

    def wire(self,decision,name=NAME):
        return json.dumps({'choices':[{'index':0,'finish_reason':'tool_calls','message':{'role':'assistant','content':None,
            'tool_calls':[{'id':'r3-call','type':'function','function':{'name':name,'arguments':json.dumps(decision)}}]}}]}).encode()

    def test_diagnosis_is_nonexecuting_and_binds_every_verified_fact(self):
        spec=schema('diagnose','a'*64,['F01','F02'])
        Draft202012Validator(spec).validate(self.decision())
        for change in (dict(action='merge'),dict(execution_authorized=True),dict(fact_ids=['F01']),
                       dict(fact_ids=['F01','F01']),dict(experiment='arbitrary_command'),dict(evidence_sha256='b'*64)):
            self.assertFalse(Draft202012Validator(spec).is_valid({**self.decision(),**change}))

    def test_cto_review_is_bound_to_exact_proposal_without_execution_authority(self):
        body=self.body('review','b'*64);contract=request_contract(body)
        expected=schema('review','a'*64,['F01','F02'],'b'*64)
        self.assertEqual(contract,expected)
        result=dict(decision='approve_experiment',evidence_sha256='a'*64,proposal_sha256='b'*64,
                    reason='Inspect current immutable delivery.',fact_ids=['F01','F02'],execution_authorized=False,release_homologated=False)
        self.assertTrue(Draft202012Validator(expected).is_valid(result))
        self.assertFalse(Draft202012Validator(expected).is_valid({**result,'proposal_sha256':'c'*64}))

    def test_missing_conflicting_contract_or_proposal_is_rejected(self):
        for extra in ('\nDELIVERY_R3_INCIDENT_V1:diagnose:'+'b'*64,
                      '\nDELIVERY_TYPED_REMEDIATION_V1:plan:'+'b'*64,
                      '\nDELIVERY_TYPED_REVIEW_V1:'+'b'*64):
            body=self.body();body['messages'][0]['content']+=extra
            with self.assertRaises(ValueError):decision_schema(body)
        with self.assertRaises(ValueError):request_contract(self.body('review'))

    def test_proxy_creates_only_nonexecuting_typed_submission(self):
        body=typed(decision_schema(self.body()))
        self.assertEqual(body['tool_choice'],{'type':'function','function':{'name':NAME}})
        output,media,receipt=translate(body,self.wire(self.decision()),'application/json')
        frame=json.loads(output)
        self.assertEqual(json.loads(frame['choices'][0]['message']['content']),self.decision())
        self.assertFalse(receipt['worker_tool_executed']);self.assertFalse(receipt['execution_authorized'])
        self.assertEqual(receipt['mode'],'r3_incident_diagnosis_or_review')

    def test_wrong_tool_true_authority_or_schema_tampering_cannot_translate(self):
        body=typed(decision_schema(self.body()))
        for decision,name in ((self.decision(),'terminal'),({**self.decision(),'execution_authorized':True},NAME)):
            with self.assertRaises(StructuredResponseRejected):translate(body,self.wire(decision,name),'application/json')
        original=decision_schema(self.body());original['response_format']['json_schema']['schema']['properties']['execution_authorized']['enum']=[True]
        with self.assertRaises(ValueError):typed(original)

    def test_unrelated_requests_are_unchanged_and_fact_count_is_bounded(self):
        self.assertIsNone(request_contract({'messages':[{'role':'user','content':'ordinary planning'}]}))
        body=self.body();body['messages'][0]['content']+='\nDELIVERY_R3_FACT:F01'
        with self.assertRaises(ValueError):request_contract(body)
        with self.assertRaises(ValueError):schema('diagnose','a'*64,[])
