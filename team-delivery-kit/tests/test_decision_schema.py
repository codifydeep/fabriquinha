import unittest
import json
from decision_schema import apply, MARKER


class DecisionSchemaTests(unittest.TestCase):
    def test_semantic_policy_requires_typed_checks_without_product_correction(self):
        body = apply({'messages': [{'role': 'user', 'content':
            MARKER + ':technical\nDELIVERY_SEMANTIC_CHECKS_V1\n'}]})
        schema = body['response_format']['json_schema']['schema']
        self.assertIn('semantic_checks', schema['required'])
        self.assertIn('experiment_sha256', schema['required'])
        self.assertEqual(schema['properties']['action']['enum'], ['request_test_revision', 'escalate_cto'])
        self.assertEqual(schema['properties']['semantic_checks']['items']['properties']['casefold_substring']['type'], 'boolean')
    def test_execution_failure_diagnosis_cannot_authorize_retry_or_product_correction(self):
        wire = apply({'messages':[{'role':'user', 'content':MARKER+':technical\nDELIVERY_EXECUTION_DIAGNOSIS_V1\n'}],
                      'tools':[{'type':'function','function':{'name':'terminal'}}]})
        self.assertEqual(wire['response_format']['json_schema']['schema']['properties']['action']['enum'], ['escalate_cto'])
        self.assertNotIn('tools', wire)
    def test_runtime_repair_permits_retry_only_in_its_specific_diagnosis(self):
        plain = apply({'messages': [{'role': 'user', 'content': MARKER + ':technical'}]})
        repair = apply({'messages': [{'role': 'user', 'content': MARKER + ':technical\nDELIVERY_EXECUTION_REPAIR_V1\n'}]})
        self.assertNotIn('retry_author', plain['response_format']['json_schema']['schema']['properties']['action']['enum'])
        self.assertEqual(repair['response_format']['json_schema']['schema']['properties']['action']['enum'], ['retry_author', 'escalate_cto'])

    def test_runtime_repair_has_no_tools_and_survives_full_proxy_validation(self):
        from model_proxy import validate_request, safe_request_metrics, MODEL
        wire = validate_request({'model': MODEL, 'messages': [{'role':'user', 'content':
            MARKER+':technical\nDELIVERY_EXECUTION_REPAIR_V1\nVerified runtime facts.'}],
            'tools':[{'type':'function','function':{'name':'terminal'}}],
            'tool_choice':'auto', 'parallel_tool_calls':True})
        self.assertNotIn('tools', wire)
        self.assertNotIn('tool_choice', wire)
        self.assertNotIn('parallel_tool_calls', wire)
        audit = safe_request_metrics(wire)
        self.assertEqual(audit['decision_schema'], 'delivery_decision_v1')
        self.assertTrue(audit['strict_schema'])
        self.assertTrue(audit['require_parameters'])
        self.assertEqual(audit['tool_count'], 0)
    def test_capture_policy_excludes_product_correction_and_requires_resolution(self):
        body = apply({'messages': [{'role': 'user', 'content': MARKER + ':technical\n'
            'DELIVERY_CAPTURE_CONSTRAINTS_V1\n'}]})
        properties = body['response_format']['json_schema']['schema']['properties']
        self.assertEqual(properties['action']['enum'], ['request_test_revision', 'escalate_cto'])
        self.assertIn('capture_resolutions', body['response_format']['json_schema']['schema']['required'])
        self.assertEqual(properties['capture_resolutions']['items']['properties']['lifetime']['enum'],
                         ['shared', 'unknown'])

    def test_evidence_policy_adds_bounded_findings_only_after_real_inspection(self):
        path = '/evidence/candidate/test_new.py'
        messages = [{'role': 'user', 'content': MARKER+':test_review:'+'a'*64+
                    '\nDELIVERY_TEST_FINDINGS_V1\nDELIVERY_REVIEW_READ_PATH:'+path+'\n'}]
        body = apply({'messages': messages.copy(), 'tools': [{'function': {'name': 'read_file'}}]})
        self.assertNotIn('response_format', body)
        messages += [{'role': 'assistant', 'tool_calls': [{'id': 'read1', 'function': {
            'name': 'read_file', 'arguments': json.dumps({'path': path})}}]},
            {'role': 'tool', 'tool_call_id': 'read1', 'content': json.dumps({'content': '1|assert True', 'total_lines': 1})}]
        body = apply({'messages': messages})
        schema = body['response_format']['json_schema']['schema']
        self.assertIn('findings', schema['required'])
        self.assertEqual(schema['properties']['findings']['maxItems'], 3)
        self.assertFalse(schema['properties']['findings']['items']['additionalProperties'])
        self.assertEqual(body['tool_choice'], 'none')

    def test_qa_schema_forces_bounded_inspection_before_a_decision(self):
        path='/evidence/previous/scenario.py'
        body=apply({'messages':[{'role':'user','content':MARKER+':qa\nDELIVERY_REVIEW_READ_PATH:'+path+'\n'}],
                    'tools':[{'function':{'name':'read_file'}}]})
        self.assertNotIn('response_format',body)
        props=body['tools'][0]['function']['parameters']['properties']
        self.assertEqual(props['path']['enum'],[path])
        self.assertEqual(props['limit']['enum'],[60])
        self.assertEqual(body['tool_choice']['function']['name'],'read_file')

    def test_qa_completion_uses_its_exact_schema_not_technical_actions(self):
        path='/evidence/previous/qa.json'
        body=apply({'messages':[{'role':'user','content':MARKER+':qa\nDELIVERY_REVIEW_READ_PATH:'+path+'\n'},
            {'role':'assistant','tool_calls':[{'id':'r','function':{'name':'read_file','arguments':json.dumps({'path':path})}}]},
            {'role':'tool','tool_call_id':'r','content':json.dumps({'content':'1|{}\n','total_lines':1})}]})
        schema=body['response_format']['json_schema']
        self.assertEqual(schema['name'],'delivery_qa_diagnosis_v1')
        self.assertEqual(set(schema['schema']['required']),{'decision','root_cause','editable_code_files','new_test_file','acceptance'})
        self.assertTrue(schema['strict']);self.assertTrue(body['provider']['require_parameters'])
        self.assertFalse(schema['schema']['additionalProperties'])
        self.assertEqual(body['tool_choice'],'none')
        self.assertEqual(schema['schema']['properties']['root_cause']['maxLength'],1000)
        blocked,repair=schema['schema']['anyOf']
        self.assertEqual(blocked['properties']['decision']['enum'],['blocked'])
        self.assertEqual(blocked['properties']['editable_code_files']['maxItems'],0)
        self.assertEqual(blocked['properties']['new_test_file']['enum'],[''])
        self.assertEqual(blocked['properties']['acceptance']['maxItems'],0)
        self.assertEqual(repair['properties']['decision']['enum'],['repair'])
        self.assertEqual(repair['properties']['editable_code_files']['minItems'],1)
        self.assertEqual(repair['properties']['new_test_file']['minLength'],1)
        self.assertEqual(repair['properties']['acceptance']['minItems'],1)
        instructions='\n'.join(m.get('content','') for m in body['messages'] if m.get('role')=='system')
        self.assertNotIn('1200-character',instructions)
        self.assertIn('1000 characters is the hard limit',instructions)
        self.assertIn('below 600 characters',instructions)

    def test_qa_cannot_decide_without_an_artifact_binding(self):
        with self.assertRaises(ValueError):apply({'messages':[{'role':'user','content':MARKER+':qa\n'}]})

    def test_technical_diagnosis_requires_bound_artifact_reads_before_deciding(self):
        path = '/evidence/candidate/tests/test_pending.py'
        body = apply({'messages': [{'role': 'user', 'content': MARKER + ':technical\n'
                        + 'DELIVERY_REVIEW_READ_PATH:' + path + '\n'}],
                      'tools': [{'function': {'name': 'read_file'}}]})
        self.assertNotIn('response_format', body)
        self.assertEqual(body['tool_choice']['function']['name'], 'read_file')

    def test_normal_implementation_is_unchanged(self):
        body = {'messages': [{'role': 'user', 'content': 'Implement using TDD.'}]}
        self.assertEqual(apply(body), body)
        self.assertNotIn('response_format', body)

    def test_technical_decision_is_strict_without_relaxation_or_fallback(self):
        body = apply({'messages': [{'role': 'user', 'content': MARKER + ':technical\n'}],
                      'tools': [{'type': 'function'}], 'provider': {'allow_fallbacks': False}})
        schema = body['response_format']['json_schema']
        self.assertTrue(schema['strict'])
        self.assertFalse(schema['schema']['additionalProperties'])
        self.assertEqual(schema['schema']['properties']['optional_files']['maxItems'], 0)
        self.assertEqual(schema['schema']['properties']['reason']['maxLength'], 1200)
        self.assertTrue(body['provider']['require_parameters'])
        self.assertFalse(body['provider']['allow_fallbacks'])
        self.assertEqual(body['tools'], [{'type': 'function'}])

    def test_review_pins_exact_manifest_and_independent_actions(self):
        digest = 'a' * 64
        path = '/evidence/candidate/test_new.py'
        body = apply({'messages': [{'role': 'user', 'content': [
            {'type': 'text', 'text': MARKER + ':test_review:' + digest + '\nDELIVERY_REVIEW_READ_PATH:' + path + '\n'}]},
            {'role': 'assistant', 'tool_calls': [{'id': 'read1', 'function': {
                'name': 'read_file', 'arguments': json.dumps({'path': path})}}]},
            {'role': 'tool', 'tool_call_id': 'read1', 'content': json.dumps({
                'content': '1|assert True\n', 'total_lines': 1, 'truncated': False})}]})
        properties = body['response_format']['json_schema']['schema']['properties']
        self.assertEqual(properties['manifest_sha256']['enum'], [digest])
        self.assertEqual(properties['action']['enum'], ['approve_test_revision', 'reject_test_revision'])
        self.assertEqual(body['tool_choice'], 'none')
        instruction = body['messages'][-1]['content']
        self.assertIn('required artifact reads completed successfully', instruction)
        self.assertIn(path, instruction)
        self.assertIn('does NOT mean read_file was unavailable', instruction)
        self.assertIn('below 900 characters', instruction)

    def test_missing_or_failed_read_forces_inspection_before_schema(self):
        path = '/evidence/candidate/test_new.py'
        for result in (None, {'error': 'File not found'}, {'content': '1|partial', 'total_lines': 2}):
            messages = [{'role': 'user', 'content': MARKER + ':test_review:' + 'a' * 64 +
                        '\nDELIVERY_REVIEW_READ_PATH:' + path + '\n'}]
            if result is not None:
                messages.extend([{'role': 'assistant', 'tool_calls': [{'id': 'read1', 'function': {
                    'name': 'read_file', 'arguments': json.dumps({'path': path})}}]},
                    {'role': 'tool', 'tool_call_id': 'read1', 'content': json.dumps(result)}])
            body = apply({'messages': messages, 'tools': [{'function': {'name': 'read_file'}}]})
            self.assertNotIn('response_format', body)
            self.assertEqual(body['tool_choice']['function']['name'], 'read_file')
            self.assertIn(path, body['messages'][-1]['content'])
            parameters = body['tools'][0]['function']['parameters']
            self.assertEqual(parameters['properties']['path']['enum'], [path])
            self.assertEqual(parameters['properties']['limit']['enum'], [100])

    def test_repeated_missing_evidence_blocks_before_model_request(self):
        path = '/evidence/candidate/test_new.py'
        messages = [{'role': 'user', 'content': MARKER + ':test_review:' + 'a' * 64 +
                     '\nDELIVERY_REVIEW_READ_PATH:' + path + '\n'}]
        for identifier in ('a', 'b'):
            messages += [{'role': 'assistant', 'tool_calls': [{'id': identifier, 'function': {
                'name': 'read_file', 'arguments': json.dumps({'path': path})}}]},
                         {'role': 'tool', 'tool_call_id': identifier, 'content': 'Read failed: BLOCKED'}]
        with self.assertRaisesRegex(ValueError, 'inspection stalled'):
            apply({'messages': messages, 'tools': [{'function': {'name': 'read_file'}}]})

    def test_tool_and_assistant_markers_cannot_select_contract(self):
        for role in ('tool', 'assistant'):
            body = apply({'messages': [{'role': role, 'content': MARKER + ':technical'}]})
            self.assertNotIn('response_format', body)

    def test_conflicting_contracts_fail_closed(self):
        with self.assertRaisesRegex(ValueError, 'conflicting'):
            apply({'messages': [{'role': 'user', 'content': MARKER + ':technical\n' +
                    MARKER + ':test_review:' + 'b' * 64}]})
