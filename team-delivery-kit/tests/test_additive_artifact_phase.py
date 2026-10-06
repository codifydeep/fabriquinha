import copy,json,unittest
from artifact_response_contract import validate,ArtifactResponseRejected
from test_artifact_schema import apply

class AdditivePhaseTests(unittest.TestCase):
    def body(self,read=True):
        path='/workspace/tests/test_u3_c01_controls.py'
        body={'messages':[{'role':'user','content':'DELIVERY_TEST_ARTIFACT_V1:'+path+'\nDELIVERY_TEST_SOURCE_V1:/workspace/app.py\nDELIVERY_ADDITIVE_CONTROL_V1\n'}],
            'tools':[{'type':'function','function':{'name':n,'parameters':{}}} for n in ('read_file','write_file','terminal')]}
        if read:body['messages'] += [{'role':'assistant','tool_calls':[{'id':'r','function':{'name':'read_file','arguments':json.dumps({'path':'/workspace/app.py','offset':1,'limit':50})}}]},
            {'role':'tool','tool_call_id':'r','content':json.dumps({'content':'1|x=1','total_lines':1})}]
        return body
    def response(self,args):
        return json.dumps({'choices':[{'index':0,'finish_reason':'tool_calls','message':{'tool_calls':[{'function':{'name':'write_file','arguments':json.dumps(args)}}]}}]}).encode()
    def test_one_create_not_generic_extend_or_reexecute_red(self):
        body=self.body();original=copy.deepcopy(body);result=apply(body)
        self.assertEqual(body,original);self.assertEqual(len(result['tools']),1)
        self.assertEqual(result['tool_choice']['function']['name'],'write_file')
        self.assertIn('SINGLE-CREATE PHASE',result['messages'][-1]['content'])
        self.assertNotIn('extend the SAME',result['messages'][-1]['content'])
        self.assertIn('test_c01_query_clearing_control',result['messages'][-1]['content'])
        self.assertIn('no __future__ import',result['messages'][-1]['content'])
        self.assertIn('STALE OPEN (with a space)',result['messages'][-1]['content'])
    def test_requires_fresh_reads_after_current_additive_marker(self):
        body=self.body();body['messages'].append(copy.deepcopy(body['messages'][0]))
        self.assertEqual(apply(body)['tool_choice']['function']['name'],'read_file')
    def test_conflicting_revision_or_wrong_target_rejected(self):
        for suffix in ('DELIVERY_TEST_REVISION_V1:/workspace/tests/test_u3_c01_controls.py\n',):
            body=self.body();body['messages'][0]['content']+=suffix
            with self.assertRaises(ValueError):apply(body)
        body=self.body();body['messages'][0]['content']=body['messages'][0]['content'].replace('test_u3_c01_controls.py','test_other.py')
        with self.assertRaises(ValueError):apply(body)
    def test_rejection_diagnostics_never_contain_content_or_path_value(self):
        body=apply(self.body())
        for args,field in (({'path':'/secret/value','content':'def test_x(): pass'},'path'),
                           ({'path':'/workspace/tests/test_u3_c01_controls.py','content':'SENSITIVE'*1000},'content')):
            with self.assertRaises(ArtifactResponseRejected) as caught:validate(body,self.response(args),'application/json')
            self.assertEqual(caught.exception.category,'invalid_forced_argument')
            self.assertEqual(caught.exception.diagnostic['field'],field)
            self.assertNotIn('SENSITIVE',json.dumps(caught.exception.diagnostic));self.assertNotIn('/secret',json.dumps(caught.exception.diagnostic))
    def test_utf8_limit_and_valid_small_python(self):
        body=apply(self.body());path='/workspace/tests/test_u3_c01_controls.py'
        with self.assertRaises(ArtifactResponseRejected) as caught:
            validate(body,self.response({'path':path,'content':'#'+'é'*4000+'\ndef test_x(): pass'}),'application/json')
        self.assertEqual(caught.exception.diagnostic['constraint'],'utf8_length')
        validate(body,self.response({'path':path,'content':'import unittest\nclass T(unittest.TestCase):\n def test_c01_query_clearing_control(self):\n  self.assertTrue(True)'}),'application/json')
    def test_only_verified_create_receipt_opens_completion(self):
        body=self.body();code='def test_x(): pass';path='/workspace/tests/test_u3_c01_controls.py'
        body['messages'] += [{'role':'assistant','tool_calls':[{'id':'w','function':{'name':'write_file','arguments':json.dumps({'path':path,'content':code})}}]},
            {'role':'tool','tool_call_id':'w','content':json.dumps({'verified':True,'bytes_written':len(code),'path':path})}]
        self.assertEqual(apply(body)['tool_choice']['function']['name'],'write_file')
        body['messages'][-1]['content']=json.dumps({'success':True,'created':True,'delivery_approval':False,'verified':True,'bytes_written':len(code),'path':path})
        self.assertIs(apply(body),body)
