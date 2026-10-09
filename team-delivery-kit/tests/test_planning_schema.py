import json
import unittest
from decision_schema import apply
from planning_schema import caller_response


class PlanningSchemaTests(unittest.TestCase):
    def body(self, role):
        return {'messages': [{'role': 'user', 'content': 'Verified context\nDELIVERY_PLANNING_SCHEMA_V1:' + role}],
                'tools': [{'type': 'function', 'function': {'name': 'terminal'}}]}

    def test_all_roles_use_strict_exact_role_and_no_tools(self):
        for role in ('product', 'cto', 'techlead'):
            body = apply(self.body(role))
            schema = body['response_format']['json_schema']
            self.assertTrue(schema['strict'])
            self.assertFalse(schema['schema']['additionalProperties'])
            self.assertEqual(schema['schema']['properties']['role']['enum'], [role])
            self.assertEqual(body['tool_choice'], 'none')
            self.assertEqual(body['tools'], [])
            self.assertIs(body['stream'], False)
            self.assertTrue(body['provider']['require_parameters'])

    def test_product_has_acceptance_not_architecture(self):
        props = apply(self.body('product'))['response_format']['json_schema']['schema']['properties']
        self.assertEqual(set(props), {'role', 'stories', 'business_questions'})
        self.assertEqual(props['stories']['maxItems'], 5)
        self.assertEqual(set(props['stories']['items']['properties']), {'title', 'acceptance'})

    def test_memory_review_is_exact_hash_bound_and_has_no_execution_tools(self):
        body=apply(self.body('memory_review'))
        schema=body['response_format']['json_schema']
        props=schema['schema']['properties']
        self.assertEqual(schema['name'],'planning_memory_review_v1')
        self.assertEqual(set(props),{'role','decision','entry_sha256','reason'})
        self.assertEqual(props['role']['enum'],['techlead'])
        self.assertEqual(props['decision']['enum'],['approve','reject'])
        self.assertEqual(props['entry_sha256']['pattern'],'^[a-f0-9]{64}$')
        self.assertEqual(body['tools'],[])

    def test_model_sees_same_unweakened_schema_as_validator(self):
        for role in ('product','cto','techlead'):
            body=apply(self.body(role))
            text=body['messages'][-1]['content']
            self.assertEqual(json.loads(text.split('Exact output schema: ',1)[1]),
                body['response_format']['json_schema']['schema'])
            self.assertIn('maxItems',text)

    def test_techlead_stays_subject_to_controller_semantic_validation(self):
        props = apply(self.body('techlead'))['response_format']['json_schema']['schema']['properties']
        card = props['cards']['items']
        self.assertEqual(card['properties']['owner']['enum'], ['backend_data', 'frontend', 'devops', 'quality_security'])
        self.assertEqual(card['properties']['test_command']['maxItems'], 7)
        self.assertFalse(card['additionalProperties'])

    def test_conflicting_roles_fail_closed(self):
        body = self.body('product')
        body['messages'][0]['content'] += '\nDELIVERY_PLANNING_SCHEMA_V1:cto'
        with self.assertRaisesRegex(ValueError, 'conflicting'):
            apply(body)

    def test_assistant_cannot_select_planning_contract(self):
        body = self.body('product')
        body['messages'][0]['role'] = 'assistant'
        self.assertNotIn('response_format', apply(body))

    def test_native_description_wrapper_preserves_output_contract(self):
        body = self.body('product')
        body['messages'][0]['content'] = ('Controller-verified issue context.\n'
            'Issue: FILTER-1 — product-schema1\n'
            'Description: DELIVERY_PLANNING_SCHEMA_V1:product\n'
            'YOU ARE THE PRODUCT.\nHandoff note: \nPlan from the verified issue brief only.')
        result = apply(body)
        self.assertEqual(result['response_format']['json_schema']['name'], 'planning_product_v1')

    def test_cto_contract_resolution_is_typed_not_json_inside_string(self):
        schema = apply(self.body('contract_resolution'))['response_format']['json_schema']['schema']
        props = schema['properties']
        self.assertEqual(props['role']['enum'], ['cto'])
        self.assertEqual(props['empty']['enum'], ['all', '400'])
        self.assertNotIn('technical_decisions', props)

    def test_nonstreaming_proposal_restores_native_text_without_fabricating_tools(self):
        body = apply(self.body('product'))
        content = json.dumps({'role': 'product', 'stories': [{'title': 'Service indicator',
                            'acceptance': ['Availability is visible']}], 'business_questions': []})
        raw = json.dumps({'choices': [{'message': {'content': content}, 'finish_reason': 'stop'}],
                          'usage': {'completion_tokens': 30}}).encode()
        streamed, media = caller_response(body, raw, 'application/json', True)
        self.assertEqual(media, 'text/event-stream')
        frames = [json.loads(line[6:]) for line in streamed.decode().splitlines() if line.startswith('data: {')]
        self.assertEqual(frames[0]['choices'][0]['delta']['content'], content)
        self.assertNotIn('tool_calls', frames[0]['choices'][0]['delta'])
        self.assertEqual(frames[-1]['usage']['completion_tokens'], 30)
        self.assertTrue(streamed.endswith(b'data: [DONE]\n\n'))
        self.assertEqual(caller_response(body, raw, 'application/json', False), (raw, 'application/json'))

    def test_unknown_schema_and_incomplete_or_tool_responses_are_not_converted(self):
        self.assertEqual(caller_response({}, b'{}', 'application/json', True), (b'{}', 'application/json'))
        body = apply(self.body('product'))
        for finish, message in (('length', {'content': '{}'}),
                                ('stop', {'content': '{}', 'tool_calls': [{}]})):
            raw = json.dumps({'choices': [{'message': message, 'finish_reason': finish}]}).encode()
            with self.assertRaises(ValueError):
                caller_response(body, raw, 'application/json', True)

    def test_proxy_validates_json_before_restoring_native_stream(self):
        from unittest.mock import patch
        import model_proxy as proxy
        import test_read_stream_recovery as fixtures
        fixture = fixtures.ReadStreamRecoveryTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        body = self.body('product')
        body.update(model=proxy.MODEL, stream=True)
        content = json.dumps({'role': 'product', 'stories': [{'title': 'Service indicator',
                            'acceptance': ['Availability is visible']}], 'business_questions': []})
        raw = json.dumps({'choices': [{'message': {'content': content}, 'finish_reason': 'stop'}]}).encode()
        with patch.object(proxy, 'forward', return_value=(200, raw, 'application/json')) as forward:
            reply = fixture.request(body)
        self.assertEqual(reply.status, 200)
        self.assertTrue(reply.wfile.getvalue().startswith(b'data: '))
        forwarded = forward.call_args.args[0]
        self.assertEqual(forwarded['tools'], [])
        self.assertIs(forwarded['stream'], False)
        self.assertEqual(proxy.load_calls(), 1)

    def test_proxy_invalid_proposal_is_not_repaired_or_automatically_retried(self):
        from unittest.mock import patch
        import model_proxy as proxy
        import test_read_stream_recovery as fixtures
        fixture = fixtures.ReadStreamRecoveryTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        body = self.body('product')
        body.update(model=proxy.MODEL, stream=True)
        raw = json.dumps({'choices': [{'message': {'content': 'Prose instead of a proposal'},
                                       'finish_reason': 'stop'}]}).encode()
        with patch.object(proxy, 'forward', return_value=(200, raw, 'application/json')) as forward:
            reply = fixture.request(body)
        self.assertEqual(reply.status, 502)
        self.assertEqual(json.loads(reply.wfile.getvalue()), {'error': {'code': 'structured_decision_response_invalid'}})
        forward.assert_called_once()
