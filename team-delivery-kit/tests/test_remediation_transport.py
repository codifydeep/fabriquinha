import copy
import unittest
import remediation_transport_probe as probe
import remediation_plan_contract as contract
import typed_decision_contract as typed
import json
from structured_response_contract import StructuredResponseRejected


class RemediationTransportTests(unittest.TestCase):
    def body(self):
        sha='a'*64
        return dict(messages=[dict(role='user',content='DELIVERY_TYPED_REMEDIATION_V1:plan:'+sha+
            '\nDELIVERY_REMEDIATION_PLAN_V1:'+sha+'\nDELIVERY_REMEDIATION_CRITERION:A01')],
            response_format=dict(type='json_schema',json_schema=dict(name='delivery_decision_v1',strict=True,
                schema=contract.schema('plan',sha,['A01']))))

    def test_canary_preserves_values_and_rejects_authority_and_stale_digest(self):
        proof=probe.run()
        self.assertEqual(proof['model_calls'],0)
        self.assertFalse(proof['worker_tool_executed'])
        self.assertFalse(proof['delivery_approval'])
        self.assertTrue(proof['negative_controls_passed'])

    def test_terminal_transport_exposes_only_nonexecuting_submission(self):
        result=typed.apply(self.body())
        self.assertEqual(len(result['tools']),1)
        self.assertEqual(result['tools'][0]['function']['name'],typed.REMEDIATION_NAME)
        self.assertNotIn('response_format',result)

    def test_mandatory_read_is_not_replaced_by_submission(self):
        body=self.body();body.pop('response_format')
        body['tool_choice']=dict(type='function',function=dict(name='read_file'))
        self.assertEqual(typed.apply(body),body)

    def test_missing_binding_and_conflicting_contract_rejected(self):
        for extra in ('\nDELIVERY_TYPED_REVIEW_V1:'+('b'*64),'\nDELIVERY_REMEDIATION_REVIEW_V1:'+('a'*64)):
            body=self.body();body['messages'][0]['content']+=extra
            with self.assertRaises(ValueError):typed.apply(body)
        body=self.body();body['messages'][0]['content']=body['messages'][0]['content'].replace('DELIVERY_REMEDIATION_PLAN_V1:','OTHER:')
        with self.assertRaises(ValueError):typed.apply(body)

    def test_schema_weakening_rejected(self):
        body=self.body()
        body['response_format']['json_schema']['schema']['properties']['execution_authorized']['enum']=[True,False]
        with self.assertRaises(ValueError):typed.apply(body)

    def review_body(self):
        body=self.body();body['messages'][0]['content']=body['messages'][0]['content'].replace(':plan:',':review:').replace('_PLAN_V1:','_REVIEW_V1:')
        body['messages'][0]['content']+='\n'+typed.REMEDIATION_LENGTH_MARKER
        body['response_format']['json_schema']['schema']=contract.schema('review','a'*64,['A01'])
        return typed.apply(body)

    def wire(self,value):
        return json.dumps(dict(choices=[dict(finish_reason='tool_calls',message=dict(content=None,tool_calls=[
            dict(type='function',function=dict(name=typed.REMEDIATION_NAME,arguments=json.dumps(value)))]))])).encode()

    def verdict(self):
        return dict(decision='request_changes',evidence_sha256='a'*64,plan_sha256='a'*64,reason='One precise change.',
                    execution_authorized=False,release_homologated=False)

    def test_reason_only_feedback_requires_new_arguments_preserves_verdict(self):
        body=self.review_body();bad=self.verdict();bad['reason']='x'*601
        with self.assertRaises(StructuredResponseRejected) as caught:typed.translate(body,self.wire(bad),'application/json')
        self.assertEqual(caught.exception.category,'typed_schema_maxLength')
        body['messages'].extend(caught.exception.length_feedback)
        good=self.verdict();out,_,receipt=typed.translate(body,self.wire(good),'application/json')
        self.assertEqual(json.loads(json.loads(out)['choices'][0]['message']['content']),good)
        self.assertFalse(receipt['plan_acceptance_by_proxy'])
        good['decision']='approve_plan'
        with self.assertRaises(StructuredResponseRejected) as changed:typed.translate(body,self.wire(good),'application/json')
        self.assertEqual(changed.exception.category,'typed_remediation_feedback_identity_drift')

    def test_feedback_rejects_other_invalid_fields_and_requires_marker(self):
        for mutation in ('digest','authority','unmarked'):
            body=self.review_body();bad=self.verdict();bad['reason']='x'*601
            if mutation=='digest':bad['plan_sha256']='b'*64
            elif mutation=='authority':bad['execution_authorized']=True
            else:body['messages'][0]['content']=body['messages'][0]['content'].replace(typed.REMEDIATION_LENGTH_MARKER,'')
            with self.assertRaises(StructuredResponseRejected) as caught:typed.translate(body,self.wire(bad),'application/json')
            self.assertFalse(hasattr(caught.exception,'length_feedback'))

    def test_feedback_claim_is_durable_and_once_only(self):
        import tempfile
        from pathlib import Path
        body=self.review_body();bad=self.verdict();bad['reason']='x'*601
        with self.assertRaises(StructuredResponseRejected) as caught:typed.translate(body,self.wire(bad),'application/json')
        with tempfile.TemporaryDirectory() as folder:
            counter=Path(folder)/'counter.json';counter.write_text('{"calls":0}')
            execution='aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
            self.assertIsNotNone(typed.claim_length_feedback(counter,execution,caught.exception,body,1))
            self.assertIsNone(typed.claim_length_feedback(counter,execution,caught.exception,body,1))
            with self.assertRaises(StructuredResponseRejected):typed.length_feedback_preflight(counter,execution,body)

    def test_proxy_feedback_round_trip_and_call_cap(self):
        from unittest.mock import patch
        import model_proxy as proxy
        import test_read_stream_recovery as fixtures
        for cap in (1,2):
            f=fixtures.ReadStreamRecoveryTests();f.setUp()
            try:
                body=self.review_body();body['model']=proxy.MODEL
                spec=copy.deepcopy(body['tools'][0]['function']['parameters'])
                body['response_format']=dict(type='json_schema',json_schema=dict(name='delivery_decision_v1',strict=True,schema=spec))
                body['tool_choice']='none'
                good=self.verdict();bad={**good,'reason':'x'*601}
                with patch.object(proxy,'MAX_CALLS',cap),patch.object(proxy,'forward',side_effect=[
                        (200,self.wire(bad),'application/json'),(200,self.wire(good),'application/json')]) as forward:
                    reply=f.request(body)
                self.assertEqual(reply.status,200 if cap==2 else 400)
                self.assertEqual(forward.call_count,cap)
                if cap==2:
                    revised=forward.call_args_list[1].args[0]
                    feedback=json.loads(revised['messages'][-1]['content'])
                    self.assertFalse(feedback['plan_acceptance_by_proxy'])
            finally:f.doCleanups()
