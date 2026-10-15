import copy
import json
import unittest
from jsonschema import Draft202012Validator
import calibration_incident_contract as contract
from decision_schema import apply


class IncidentContractTests(unittest.TestCase):
    def test_evidence_diagnosis_binds_prior_hold_and_actual_probe_without_authority(self):
        v=contract.context('evidence_diagnosis','a'*64,'b'*64,'c'*64,'d'*64)
        body=apply(dict(messages=[dict(role='user',content=contract.capsule(v))]))
        schema=body['response_format']['json_schema']['schema']
        self.assertEqual(schema['properties']['action']['enum'],['submit_probe_for_review','retain_technical_hold'])
        self.assertEqual(schema['properties']['proposal_sha256']['enum'],['c'*64])
        self.assertEqual(schema['properties']['probe_sha256']['enum'],['d'*64])
        self.assertEqual(body['tools'],[])
        with self.assertRaises(ValueError):contract.context('evidence_diagnosis','a'*64,'b'*64)

    def test_schema_has_no_tools_or_execution_authority_and_binds_review_hashes(self):
        for phase in ('diagnosis','review'):
            v=contract.context(phase,'a'*64,'b'*64,*((None,None) if phase=='diagnosis' else ('c'*64,'d'*64)))
            body=apply(dict(messages=[dict(role='user',content=contract.capsule(v))],tools=[dict(function=dict(name='terminal'))]))
            self.assertEqual(body['tools'],[]);self.assertEqual(body['tool_choice'],'none')
            schema=body['response_format']['json_schema']['schema'];Draft202012Validator.check_schema(schema)
            self.assertEqual(schema['properties']['historical_cause_proven']['enum'],[False])
            if phase=='review':self.assertEqual(schema['properties']['probe_sha256']['enum'],['d'*64])

    def test_duplicate_forged_or_nonuser_context_cannot_select_incident(self):
        v=contract.context('diagnosis','a'*64,'b'*64);note=contract.capsule(v)
        for role in ('assistant','system','tool'):self.assertIsNone(contract.request(dict(messages=[dict(role=role,content=note)])))
        for content in (note+note,note.replace('"diagnosis"','"review"')):
            with self.assertRaises(ValueError):contract.request(dict(messages=[dict(role='user',content=content)]))

    def test_current_submission_and_incident_cannot_be_mixed(self):
        import calibration_response_contract as submission
        note=contract.capsule(contract.context('diagnosis','a'*64,'b'*64))+submission.capsule(
            submission.context('bundle',['/evidence/candidate/test.py'],'c'*64))
        with self.assertRaises(ValueError):apply(dict(messages=[dict(role='user',content=note)]))

    def test_proxy_pipeline_uses_incident_contract_before_historical_markers(self):
        import model_proxy
        note='DELIVERY_TYPED_DECISION_V1\nDELIVERY_TEST_ARTIFACT_V1:/workspace/tests/test_old.py\n'+contract.capsule(
            contract.context('diagnosis','a'*64,'b'*64))
        value=model_proxy.validate_request(dict(model=model_proxy.MODEL,messages=[dict(role='user',content=note)],
            tools=[dict(type='function',function=dict(name='terminal',parameters={}))]))
        self.assertEqual(value['response_format']['json_schema']['name'],'delivery_calibration_incident_v1')
        self.assertEqual(value['tools'],[])

    def test_duplicate_context_keys_are_not_canonical_even_with_same_value(self):
        note=contract.capsule(contract.context('diagnosis','a'*64,'b'*64))
        note=note.replace('"phase":"diagnosis"','"phase":"diagnosis","phase":"diagnosis"')
        with self.assertRaises(ValueError):contract.request(dict(messages=[dict(role='user',content=note)]))
