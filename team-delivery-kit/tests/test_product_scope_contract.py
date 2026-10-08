import copy
import json
import unittest
from decision_schema import apply
from product_scope_contract import instruction


class ProductScopeContractTests(unittest.TestCase):
    def setUp(self):
        self.context=dict(issue_id='issue', source_task='source', contract_sha256='a'*64,
            snapshot_sha256='b'*64, failure_output_sha256='c'*64,
            eligible_code_sha256={'app/db.py':'d'*64, 'app/store.py':'e'*64},
            frozen_test_sha256={'tests/test_new.py':'f'*64})

    def body(self, kind='proposal', proposal_sha256=None):
        return {'messages':[{'role':'user','content':instruction(kind,self.context,proposal_sha256)}],
                'tools':[{'type':'function','function':{'name':'read_file'}},
                         {'type':'function','function':{'name':'terminal'}}]}

    def inspected(self, body):
        for i,path in enumerate(sorted(self.context['eligible_code_sha256'])):
            identifier=str(i)
            body['messages'] += [dict(role='assistant',tool_calls=[dict(id=identifier,
                function=dict(name='read_file',arguments=json.dumps({'path':'/evidence/candidate/'+path,
                    'offset':1,'limit':100})))]), dict(role='tool',tool_call_id=identifier,
                content=json.dumps({'content':'1|code','total_lines':1}))]
        return body

    def test_all_dependency_reads_are_required_and_only_read_tool_is_available(self):
        body=apply(self.body())
        self.assertNotIn('response_format',body)
        self.assertEqual(len(body['tools']),1)
        self.assertEqual(body['tool_choice']['function']['name'],'read_file')
        self.assertEqual(body['tools'][0]['function']['parameters']['properties']['path']['enum'],
            ['/evidence/candidate/app/db.py'])

    def test_proposal_schema_binds_failure_and_only_known_code_paths(self):
        body=apply(self.inspected(self.body()))
        schema=body['response_format']['json_schema']['schema']
        self.assertEqual(schema['properties']['operation']['enum'],['propose_product_scope_revision_v1'])
        self.assertEqual(schema['properties']['failure_output_sha256']['enum'],['c'*64])
        self.assertEqual(schema['properties']['write_files']['items']['enum'],['app/db.py','app/store.py'])
        self.assertFalse(schema['additionalProperties'])

    def test_review_binds_exact_proposal_and_has_no_write_selection(self):
        body=apply(self.inspected(self.body('review','1'*64)))
        props=body['response_format']['json_schema']['schema']['properties']
        self.assertEqual(props['proposal_sha256']['enum'],['1'*64])
        self.assertEqual(props['decision']['enum'],['approve','request_changes'])
        self.assertNotIn('write_files',props)

    def test_mixed_or_tampered_context_is_rejected(self):
        body=self.body()
        for content in (body['messages'][0]['content']+'\nDELIVERY_STRUCTURED_DECISION_V1:technical',
                        body['messages'][0]['content'].replace('app/db.py','app/other.py')):
            with self.subTest(content=content),self.assertRaises(ValueError):
                apply(dict(body,messages=[dict(role='user',content=content)]))
        bad=copy.deepcopy(self.context)
        bad['eligible_code_sha256']={'tests/test_old.py':'d'*64}
        with self.assertRaises(ValueError):instruction('proposal',bad)

    def test_typed_submission_is_nonexecuting_and_read_gate_survives(self):
        from typed_decision_contract import apply as typed, NAME
        pending=typed(apply(self.body()))
        self.assertEqual(pending['tool_choice']['function']['name'],'read_file')
        ready=typed(apply(self.inspected(self.body())))
        self.assertEqual(ready['tool_choice']['function']['name'],NAME)
        self.assertEqual(len(ready['tools']),1)
        self.assertNotIn('response_format',ready)
        self.assertEqual(ready['tools'][0]['function']['parameters']['properties']['operation']['enum'],
                         ['propose_product_scope_revision_v1'])

    def test_complete_proxy_pipeline_keeps_read_gate_and_typed_scope_schema(self):
        from model_proxy import validate_request, MODEL
        pending=validate_request(dict(self.body(),model=MODEL))
        self.assertEqual(pending['tool_choice']['function']['name'],'read_file')
        ready=validate_request(dict(self.inspected(self.body()),model=MODEL))
        self.assertEqual(ready['tools'][0]['function']['parameters']['properties']['operation']['enum'],
                         ['propose_product_scope_revision_v1'])

    def test_proxy_translation_preserves_actual_arguments_and_rejects_prose_or_unlisted_paths(self):
        from typed_decision_contract import apply as typed, translate, NAME
        from structured_response_contract import StructuredResponseRejected
        ready=typed(apply(self.inspected(self.body())))
        proposal={k:v['enum'][0] for k,v in ready['tools'][0]['function']['parameters']['properties'].items()
                  if 'enum' in v}
        proposal.update(write_files=['app/store.py'],reason='Add the missing persistence lookup.')
        def wire(value,content=None):
            return json.dumps({'choices':[{'finish_reason':'tool_calls','message':{'content':content,
                'tool_calls':[{'type':'function','function':{'name':NAME,'arguments':json.dumps(value)}}]}}]}).encode()
        output,_,receipt=translate(ready,wire(proposal),'application/json')
        self.assertEqual(json.loads(output)['choices'][0]['message']['content'],
                         json.dumps(proposal,sort_keys=True,separators=(',',':')))
        self.assertFalse(receipt['worker_tool_executed'])
        self.assertFalse(receipt['delivery_approval'])
        for value,content in ((dict(proposal,write_files=['tests/test_new.py']),None),
                              (dict(proposal,failure_output_sha256='0'*64),None),(proposal,'I approve')):
            with self.subTest(value=value,content=content),self.assertRaises(StructuredResponseRejected):
                translate(ready,wire(value,content),'application/json')
