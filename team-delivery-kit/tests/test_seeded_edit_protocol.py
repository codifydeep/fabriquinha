import json
import unittest

import test_test_artifact_schema as fixtures
from test_artifact_schema import apply
from artifact_response_contract import validate, ArtifactResponseRejected


class SeededEditProtocolTests(unittest.TestCase):
    def test_byte_guidance_comes_from_complete_read_without_increasing_write_authority(self):
        body=self.body()
        text='# '+('é'*16000)
        body['messages'][-1]['content']=json.dumps(dict(content='1|'+text,total_lines=1))
        result=apply(body)
        note=result['messages'][-1]['content']
        self.assertIn('byte ceiling='+str(len(text.encode('utf-8'))+1),note)
        self.assertIn('write limit32768',note)
        self.assertIn('preserving every method/assertion',note)
        chosen=next(t for t in result['tools'] if t['function']['name']=='patch')
        self.assertEqual(chosen['function']['parameters']['properties']['path']['enum'],['/workspace/tests/test_new.py'])
        self.assertEqual(chosen['function']['parameters']['properties']['new_string']['maxLength'],4096)

    def test_real_edit_does_not_rearm_pre_edit_read_gate_after_changed_file_read(self):
        body=self.body()
        body['messages'] += [{'role':'assistant','tool_calls':[{'id':'edit','function':{
            'name':'patch','arguments':json.dumps({'path':'/workspace/tests/test_new.py','old_string':'before','new_string':'after'})}}]},
            {'role':'tool','tool_call_id':'edit','content':json.dumps({'success':True,'diff':'changed'})},
            {'role':'assistant','tool_calls':[{'id':'reread','function':{'name':'read_file',
                'arguments':json.dumps({'path':'/workspace/tests/test_new.py','offset':1,'limit':200})}}]},
            {'role':'tool','tool_call_id':'reread','content':json.dumps({'content':'1|def test_x(): assert True','total_lines':1})}]
        self.assertIs(apply(body),body)

    def test_edit_before_complete_inspection_does_not_waive_read_gate(self):
        body=self.body();body['messages']=body['messages'][:1]+[
            {'role':'assistant','tool_calls':[{'id':'edit','function':{'name':'patch',
                'arguments':json.dumps({'path':'/workspace/tests/test_new.py','old_string':'before','new_string':'after'})}}]},
            {'role':'tool','tool_call_id':'edit','content':json.dumps({'success':True,'diff':'changed'})}]
        self.assertEqual(apply(body)['tool_choice']['function']['name'],'read_file')
    def test_seeded_revision_batches_real_reads_without_waiving_completeness(self):
        body=self.body()
        body['messages']=body['messages'][:1]
        result=apply(body)
        read=next(t['function'] for t in result['tools'] if t['function']['name']=='read_file')
        self.assertEqual(read['parameters']['properties']['limit']['enum'],[200])
        self.assertEqual(result['tool_choice']['function']['name'],'read_file')
        self.assertEqual(read['parameters']['properties']['offset']['enum'],[1])

    def body(self):
        fixture=fixtures.TestArtifactSchemaTests()
        body=fixture.body(read=True)
        body['messages'][0]['content']+='DELIVERY_TEST_REVISION_V1:/workspace/tests/test_new.py\nDELIVERY_SEEDED_EDIT_REQUIRED_V1:/workspace/tests/test_new.py\n'
        body['tools'].append({'type':'function','function':{'name':'patch','parameters':{}}})
        body['messages'] += [{'role':'assistant','tool_calls':[{'id':'target-read','function':{
            'name':'read_file','arguments':json.dumps({'path':'/workspace/tests/test_new.py','offset':1,'limit':50})}}]},
            {'role':'tool','tool_call_id':'target-read','content':json.dumps({'content':'1|def test_x(): assert False','total_lines':1})}]
        return body

    def test_requires_actual_targeted_edit_after_reads_not_text(self):
        body=self.body()
        body['messages'].append({'role':'assistant','content':'I will fix it.'})
        result=apply(body)
        self.assertEqual(result['tool_choice']['function']['name'],'patch')
        self.assertEqual(result['tools'][-1]['function']['parameters']['properties']['path']['enum'],['/workspace/tests/test_new.py'])

    def test_only_successful_real_diff_releases_initial_edit_gate(self):
        for receipt,released in [({'success':True,'diff':'@@ changed'},True),
                                 ({'success':True,'diff':'@@ changed','no_change':True},False),
                                 ({'success':True,'diff':'','already_applied':True},False),
                                 ({'success':False,'error':'denied'},False)]:
            with self.subTest(receipt=receipt):
                body=self.body()
                body['messages'] += [{'role':'assistant','tool_calls':[{'id':'edit','function':{
                    'name':'patch','arguments':json.dumps({'path':'/workspace/tests/test_new.py','old_string':'before','new_string':'after'})}}]},
                    {'role':'tool','tool_call_id':'edit','content':json.dumps(receipt)}]
                result=apply(body)
                self.assertEqual(result is body,released)

    def test_transport_rejects_noop_and_wrong_target_patch(self):
        body=apply(self.body())
        for args in [{'path':'/workspace/tests/test_new.py','old_string':'same','new_string':'same'},
                     {'path':'/workspace/app.py','old_string':'before','new_string':'after'}]:
            payload={'choices':[{'index':0,'finish_reason':'tool_calls','message':{
                'tool_calls':[{'function':{'name':'patch','arguments':json.dumps(args)}}]}}]}
            with self.assertRaises(ArtifactResponseRejected):
                validate(body,json.dumps(payload).encode(),'application/json')
