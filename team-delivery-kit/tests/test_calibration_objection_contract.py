import json
import unittest
from jsonschema import Draft202012Validator
import calibration_objection_contract as contract
from decision_schema import apply


class ObjectionContractTests(unittest.TestCase):
    def test_referral_binds_all_evidence_hashes_and_has_no_execution_authority(self):
        context=contract.context('a'*64,'b'*64,'c'*64)
        body=apply(dict(messages=[dict(role='user',content=contract.capsule(context))],tools=[dict(function=dict(name='terminal'))]))
        self.assertEqual(body['tools'],[]);self.assertEqual(body['tool_choice'],'none')
        schema=body['response_format']['json_schema']['schema']
        value={**context,'action':'refer_to_cto','reason':'Measured seam supports another proposal',
            'author_retry_authorized':False,'execution_authorized':False,'delivery_approval':False}
        Draft202012Validator(schema).validate(value)
        for bad in ({**value,'delivery_approval':True},{**value,'probe_sha256':'d'*64},{**value,'action':'approve_calibration'}):
            self.assertFalse(Draft202012Validator(schema).is_valid(bad))

    def test_nonuser_duplicate_or_mixed_context_cannot_select_the_contract(self):
        note=contract.capsule(contract.context('a'*64,'b'*64,'c'*64))
        self.assertIsNone(contract.request(dict(messages=[dict(role='assistant',content=note)])))
        with self.assertRaises(ValueError):contract.request(dict(messages=[dict(role='user',content=note+note)]))
        from calibration_incident_contract import capsule,context
        with self.assertRaises(ValueError):contract.apply(dict(messages=[dict(role='user',content=note+capsule(context('diagnosis','d'*64,'e'*64)))]))
