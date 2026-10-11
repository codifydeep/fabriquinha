import copy
import json
import unittest
from jsonschema import Draft202012Validator
import calibration_response_contract as contract
from decision_schema import apply
from structured_response_contract import validate,StructuredResponseRejected
from artifact_read_evidence import observations

PATH='/evidence/candidate/tests/test_contract.py'


def receipt(path=PATH):
    return [dict(role='assistant',tool_calls=[dict(id='read',type='function',function=dict(
        name='read_file',arguments=json.dumps(dict(path=path,offset=1,limit=100))))]),
        dict(role='tool',tool_call_id='read',content=json.dumps(dict(content='1|source',total_lines=1)))]


class CalibrationContractTests(unittest.TestCase):
    def test_native_handoff_wrapper_keeps_current_capsule_and_nonuser_claims_cannot_select_it(self):
        body=self.body()
        current=body['messages'][0]['content']
        body['messages'][0]['content']='Handoff note: DELIVERY_PLANNING_START marker\nSource: task\n'+current
        self.assertEqual(contract.request(body)['phase'],'bundle')
        for role in ('assistant','tool','system'):
            self.assertIsNone(contract.request(dict(messages=[dict(role=role,content=current)])))

    def test_false_tool_arguments_and_duplicate_json_are_rejected(self):
        body=apply(self.body(complete=True))
        for arguments in (json.dumps(dict(path=PATH,offset=True,limit=100)),
                json.dumps(dict(path=PATH,offset=1,limit=101)),
                '{"path":"'+PATH+'","path":"/secret/key","offset":1,"limit":100}'):
            raw=json.dumps(dict(choices=[dict(finish_reason='tool_calls',message=dict(tool_calls=[
                dict(function=dict(name='read_file',arguments=arguments))]))])).encode()
            with self.assertRaises(StructuredResponseRejected):validate(body,raw,'application/json')

    def test_real_public_bundle_matches_current_schema_without_old_optional_files(self):
        from test_generic_calibration_proposal import ProposalTests
        fixture=ProposalTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        value=contract.context('bundle',[PATH],'a'*64)
        Draft202012Validator(contract.schema(value)).validate(fixture.body)

    def test_streamed_extra_read_is_checked_and_incomplete_or_legacy_calls_fail_closed(self):
        body=apply(self.body(complete=True))
        call=dict(index=0,function=dict(name='read_file',arguments=json.dumps(dict(
            path='/evidence/candidate/app/value.txt',offset=1,limit=100))))
        frames=[dict(choices=[dict(index=0,delta={'tool_calls':[call]},finish_reason=None)]),
            dict(choices=[dict(index=0,delta={},finish_reason='tool_calls')])]
        raw=''.join('data: '+json.dumps(f)+'\n\n' for f in frames)+'data: [DONE]\n\n'
        validate(body,raw.encode(),'text/event-stream')
        with self.assertRaises(StructuredResponseRejected):validate(body,raw.removesuffix('data: [DONE]\n\n').encode(),'text/event-stream')
        frames[0]['choices'][0]['delta']={'function_call':call['function']}
        raw=''.join('data: '+json.dumps(f)+'\n\n' for f in frames)+'data: [DONE]\n\n'
        with self.assertRaises(StructuredResponseRejected):validate(body,raw.encode(),'text/event-stream')

    def body(self,phase='bundle',complete=False):
        value=contract.context(phase,[PATH],'a'*64,*((None,None) if phase=='bundle' else ('b'*64,'c'*64)))
        messages=[dict(role='user',content='DELIVERY_STRUCTURED_DECISION_V1:technical\n'+contract.capsule(value))]
        if complete:messages+=receipt()
        return dict(messages=messages,tools=[dict(type='function',function=dict(name='read_file',parameters={})),
            dict(type='function',function=dict(name='terminal',parameters={}))])

    def test_current_contract_forces_actual_read_despite_historical_technical_marker(self):
        body=apply(self.body())
        self.assertEqual(body['tool_choice']['function']['name'],'read_file')
        self.assertEqual(len(body['tools']),1);self.assertNotIn('response_format',body)
        self.assertEqual(body['tools'][0]['function']['parameters']['properties']['path']['enum'],[PATH])

    def test_producer_can_inspect_extra_product_source_but_not_terminal_or_credentials(self):
        body=apply(self.body(complete=True));self.assertEqual(body['tool_choice'],'auto')
        def reply(name,path):
            return json.dumps(dict(choices=[dict(finish_reason='tool_calls',message=dict(tool_calls=[dict(function=dict(
                name=name,arguments=json.dumps(dict(path=path,offset=1,limit=100))))]))])).encode()
        validate(body,reply('read_file','/evidence/candidate/app/value.txt'),'application/json')
        for name,path in (('terminal',PATH),('read_file','/secret/key'),('read_file','/evidence/candidate/../key')):
            with self.assertRaises(StructuredResponseRejected):validate(body,reply(name,path),'application/json')

    def test_terminal_artifact_is_validated_locally_and_cannot_grant_authority(self):
        body=apply(self.body(complete=True))
        artifact=dict(action='calibration_objection',reason='Unsupported seam',execution_authorized=False,delivery_approval=False)
        def reply(item):return json.dumps(dict(choices=[dict(finish_reason='stop',message=dict(content=json.dumps(item)))])).encode()
        validate(body,reply(artifact),'application/json')
        for invalid in ({**artifact,'delivery_approval':True},dict(action='request_correction',reason='old contract',optional_files=[])):
            with self.assertRaises(StructuredResponseRejected):validate(body,reply(invalid),'application/json')

    def test_policy_decision_schema_is_bound_to_exact_hashes_and_phase(self):
        body=apply(self.body('review',True))
        self.assertEqual(body['tool_choice'],'none');self.assertEqual(body['tools'],[])
        schema=body['response_format']['json_schema']['schema'];Draft202012Validator.check_schema(schema)
        good=dict(action='approve_calibration',policy_sha256='b'*64,controls_manifest_sha256='c'*64,
            execution_authorized=False,delivery_approval=False)
        Draft202012Validator(schema).validate(good)
        self.assertFalse(Draft202012Validator(schema).is_valid({**good,'policy_sha256':'d'*64}))

    def test_duplicate_or_hash_changed_capsules_are_rejected(self):
        body=self.body();body['messages']*=2
        with self.assertRaises(ValueError):apply(body)
        body=self.body();body['messages'][0]['content']=body['messages'][0]['content'].replace('"bundle"','"review"')
        with self.assertRaises(ValueError):apply(body)

    def test_control_and_policy_native_read_receipts_are_recognized_without_trusting_claims(self):
        for path in ('/evidence/controls/positive.txt','/evidence/policy/policy.json'):
            messages=[dict(type='tool_use',tool='read_file',call_id='read',input={'text':path}),
                dict(type='tool_result',call_id='read',output='Read '+path+' — 1 total lines\n\n```\n1|source\n```')]
            self.assertIn(path,observations(messages))
        self.assertEqual(observations([dict(role='assistant',content='I read the policy')]),{})
