import copy
import unittest
import remediation_transport_probe as probe
import remediation_plan_contract as contract
import typed_decision_contract as typed


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
