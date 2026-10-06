import copy
import json
import unittest
from jsonschema import Draft202012Validator
from decision_schema import apply
from observed_finding_locations import MARKER
from typed_decision_contract import apply as typed, translate, REVIEW_NAME
from structured_response_contract import StructuredResponseRejected


class ObservedFindingLocationTests(unittest.TestCase):
    def setUp(self):
        self.path='/evidence/candidate/tests/test_new.py';self.sha='a'*64
        self.source='class Cases:\n    def test_actual(self):\n        self.assertTrue(True)\n'
        self.messages=[{'role':'user','content':
            'DELIVERY_STRUCTURED_DECISION_V1:test_review:'+self.sha+'\nDELIVERY_TYPED_REVIEW_V1:'+self.sha+
            '\nDELIVERY_TEST_FINDINGS_V1\n'+MARKER+'\nDELIVERY_REVIEW_READ_PATH:'+self.path+'\n'},
            {'role':'assistant','tool_calls':[{'id':'read','function':{'name':'read_file',
                'arguments':json.dumps({'path':self.path,'offset':1,'limit':100})}}]},
            {'role':'tool','tool_call_id':'read','content':json.dumps({'total_lines':3,
                'content':'1|class Cases:\n2|    def test_actual(self):\n3|        self.assertTrue(True)'})}]
        self.finding=dict(kind='missing_coverage',tree='candidate',path='tests/test_new.py',
            test='Cases.test_actual',line=3,quote='self.assertTrue(True)',
            expected='Exercise real application behavior.',observed='Only a constant is asserted.')
        self.decision=dict(action='reject_test_revision',manifest_sha256=self.sha,
            reason='The test does not exercise the application.',optional_files=[],findings=[self.finding])

    def schema(self):return apply({'messages':copy.deepcopy(self.messages)})['response_format']['json_schema']['schema']

    def test_only_exact_observed_location_combinations_are_admissible(self):
        validator=Draft202012Validator(self.schema());validator.validate(self.decision)
        for change in ({'test':'Cases'},{'test':'Cases.test_invented'},{'line':2},
                       {'quote':'self.assertFalse(False)'},{'tree':'previous'},{'path':'other.py'}):
            decision=copy.deepcopy(self.decision);decision['findings'][0].update(change)
            with self.subTest(change=change):self.assertFalse(validator.is_valid(decision))

    def test_module_location_and_empty_approval_are_still_valid(self):
        decision=copy.deepcopy(self.decision)
        decision['findings'][0].update(test='__module__',line=1,quote='class Cases:')
        Draft202012Validator(self.schema()).validate(decision)
        decision.update(action='approve_test_revision',findings=[])
        Draft202012Validator(self.schema()).validate(decision)
        decision['findings']=[self.finding]
        self.assertFalse(Draft202012Validator(self.schema()).is_valid(decision))

    def test_incomplete_read_is_not_a_verdict_or_citation_choice(self):
        self.messages[-1]['content']=json.dumps({'total_lines':3,'content':'1|class Cases:'})
        body=apply({'messages':self.messages,'tools':[{'type':'function','function':{'name':'read_file'}}]})
        self.assertNotIn('response_format',body)
        self.assertEqual(body['tool_choice']['function']['name'],'read_file')

    def test_selection_survives_typed_transport_without_repairing_model_values(self):
        body=typed(apply({'messages':copy.deepcopy(self.messages)}))
        def wire(decision):return json.dumps({'choices':[{'finish_reason':'tool_calls','message':{
            'content':None,'tool_calls':[{'type':'function','function':{'name':REVIEW_NAME,
                'arguments':json.dumps(decision)}}]}}]}).encode()
        out,_,receipt=translate(body,wire(self.decision),'application/json')
        self.assertEqual(json.loads(json.loads(out)['choices'][0]['message']['content']),self.decision)
        self.assertTrue(receipt['model_values_preserved'])
        self.assertFalse(receipt['review_acceptance_by_proxy'])
        bad=copy.deepcopy(self.decision);bad['findings'][0]['test']='Cases'
        with self.assertRaises(StructuredResponseRejected):translate(body,wire(bad),'application/json')

    def test_unmarked_contract_is_unchanged_and_no_assistant_claim_creates_source(self):
        self.messages[0]['content']=self.messages[0]['content'].replace(MARKER+'\n','')
        self.assertNotIn('anyOf',self.schema()['properties']['findings']['items'])
        from observed_finding_locations import constrain
        with self.assertRaises(ValueError):constrain({},[{'role':'assistant','content':self.source}],{self.path})

    def test_cto_uses_typed_observed_diagnosis_without_approval_or_write_actions(self):
        messages=copy.deepcopy(self.messages)
        messages[0]['content']=messages[0]['content'].replace('test_review:'+self.sha,'technical').replace(
            'DELIVERY_TYPED_REVIEW_V1:'+self.sha,'DELIVERY_TYPED_DECISION_V1\nDELIVERY_TYPED_TEST_DIAGNOSIS_V1')
        body=typed(apply({'messages':messages}))
        schema=body['tools'][0]['function']['parameters']
        decision={k:v for k,v in self.decision.items() if k!='manifest_sha256'}
        decision['action']='request_test_revision'
        Draft202012Validator(schema).validate(decision)
        for action in ('approve_test_revision','request_correction','retry_author'):
            self.assertFalse(Draft202012Validator(schema).is_valid({**decision,'action':action}))
        bad=copy.deepcopy(body);bad['tools'][0]['function']['parameters']['properties']['findings']['items'].pop('anyOf')
        # Construction fails closed if the observed-location constraint is absent.
        original=apply({'messages':messages})
        original['response_format']['json_schema']['schema']['properties']['findings']['items'].pop('anyOf')
        with self.assertRaises(ValueError):typed(original)
