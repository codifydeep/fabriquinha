import json
import unittest
from jsonschema import Draft202012Validator
import calibration_experiment_contract as contract
from decision_schema import apply


class ExperimentContractTests(unittest.TestCase):
    def test_design_and_review_cannot_approve_delivery_or_skip_independence(self):
        for phase in ('design','review'):
            ctx=contract.context(phase,'a'*64,'b'*64,'c'*64)
            body=apply(dict(messages=[dict(role='user',content=contract.capsule(ctx))],tools=[dict(function=dict(name='terminal'))]))
            self.assertEqual(body['tools'],[]);self.assertEqual(body['tool_choice'],'none')
            value={**ctx,'action':'propose_fixture_experiment' if phase=='design' else 'permit_fixture_draft',
                'reason':'An experiment plan, not a result','author_retry_authorized':False,'execution_authorized':False,'delivery_approval':False}
            if phase=='design':value.update(hypothesis='Frozen Path controls are sufficient',method='Run full frozen harness on references',expected_evidence='Positive pass, criterion negatives fail')
            validator=Draft202012Validator(body['response_format']['json_schema']['schema']);validator.validate(value)
            for bad in ({**value,'execution_authorized':True},{**value,'action':'approve_calibration'},{**value,'source_sha256':'d'*64}):
                self.assertFalse(validator.is_valid(bad))

    def test_duplicate_mixed_and_nonuser_capsules_cannot_choose_phase(self):
        note=contract.capsule(contract.context('design','a'*64,'b'*64,'c'*64))
        self.assertIsNone(contract.request(dict(messages=[dict(role='assistant',content=note)])))
        with self.assertRaises(ValueError):contract.request(dict(messages=[dict(role='user',content=note+note)]))
        import calibration_objection_contract as objection
        with self.assertRaises(ValueError):contract.apply(dict(messages=[dict(role='user',content=note+objection.capsule(objection.context('a'*64,'b'*64,'c'*64)))]))
        malformed=note.replace('"phase":"design"','"phase":"design","phase":"review"')
        with self.assertRaises(ValueError):contract.request(dict(messages=[dict(role='user',content=malformed)]))
