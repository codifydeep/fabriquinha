import json
import unittest
from calibration_diagnostic_probe import build, summarize_reply, attach_dependencies,prepared_identity
from calibration_response_contract import capsule, context


class DiagnosticProbeTests(unittest.TestCase):
    def setUp(self):
        self.experiment='11111111-1111-4111-8111-111111111111'
        self.task='22222222-2222-4222-8222-222222222222'
        self.path='/evidence/candidate/tests/test_one.py'
        self.note=capsule(context('bundle',[self.path],'a'*64))
        self.reads=[dict(type='tool_use',tool='read_file',call_id='read1',input={'path':self.path}),
            dict(type='tool_result',tool='read_file',call_id='read1',output=
                'Read '+self.path+' — 1 total lines\n\n```\n1|pass\n```')]

    def test_preserved_inputs_are_not_native_proof_or_permission(self):
        body,receipt=build(self.note,self.reads,'model',self.experiment,self.task)
        self.assertEqual(len(body['messages']),4)
        for field in ('native_read_evidence','execution_authorized','delivery_approval',
                      'workflow_transition','tool_execution_allowed'):
            self.assertIs(receipt[field],False)

    def test_missing_foreign_or_duplicate_read_is_rejected(self):
        for reads in ([],self.reads*2,[self.reads[0],dict(self.reads[1],call_id='foreign')]):
            with self.assertRaises(ValueError):build(self.note,reads,'model',self.experiment,self.task)

    def test_cannot_impersonate_task_or_switch_phase(self):
        with self.assertRaises(ValueError):build(self.note,self.reads,'model',self.task,self.task)
        note=capsule(context('review',[self.path],'a'*64,'b'*64,'c'*64))
        with self.assertRaises(ValueError):build(note,self.reads,'model',self.experiment,self.task)

    def test_extra_reads_cannot_include_other_workspaces_or_credentials(self):
        for path in ('/delivery/secret.txt','/secret/openrouter.key',
                     '/evidence/policy/policy.json','/evidence/candidate/../secret'):
            extra=[dict(self.reads[0],call_id='extra',input={'path':path}),
                dict(self.reads[1],call_id='extra')]
            with self.assertRaises(ValueError):
                build(self.note,self.reads+extra,'model',self.experiment,self.task)

    def test_partial_pages_do_not_manufacture_complete_inspection(self):
        reads=[self.reads[0],dict(self.reads[1],output=
            'Read '+self.path+' — 2 total lines\n\n```\n1|pass\n```')]
        with self.assertRaises(ValueError):build(self.note,reads,'model',self.experiment,self.task)

    def test_oversized_output_is_rejected_before_transport(self):
        reads=[self.reads[0],dict(self.reads[1],output='x'*131073)]
        with self.assertRaises(ValueError):build(self.note,reads,'model',self.experiment,self.task)

    def test_read_requests_are_preserved_without_executing_or_disclosing_content(self):
        body,_=build(self.note,self.reads,'model',self.experiment,self.task)
        args={'path':'/evidence/candidate/web/lobby.html','offset':1,'limit':100}
        data=json.dumps({'choices':[{'finish_reason':'tool_calls','message':{
            'tool_calls':[{'function':{'name':'read_file','arguments':json.dumps(args)}}]}}]}).encode()
        result=summarize_reply(body,data)
        self.assertEqual(result['requested_reads'],[args])
        self.assertIs(result['tool_execution_allowed'],False)
        self.assertIs(result['delivery_approval'],False)

    def test_objection_is_format_observation_not_workflow_transition(self):
        body,_=build(self.note,self.reads,'model',self.experiment,self.task)
        content=json.dumps(dict(action='calibration_objection',reason='private detail',
            execution_authorized=False,delivery_approval=False))
        data=json.dumps({'choices':[{'finish_reason':'stop','message':{'content':content}}]}).encode()
        result=summarize_reply(body,data)
        self.assertEqual(result['action'],'calibration_objection')
        self.assertNotIn('private detail',json.dumps(result))
        self.assertIs(result['workflow_transition'],False)

    def test_invalid_reply_is_not_promoted_to_diagnostic_success(self):
        body,_=build(self.note,self.reads,'model',self.experiment,self.task)
        for content in ('not json',json.dumps({'action':'approve','delivery_approval':True})):
            data=json.dumps({'choices':[{'finish_reason':'stop','message':{'content':content}}]}).encode()
            with self.assertRaises(ValueError):summarize_reply(body,data)

    def test_complete_dependency_context_never_adds_native_tool_receipts(self):
        body,_=build(self.note,self.reads,'model',self.experiment,self.task)
        page=dict(output=json.dumps({'total_lines':1,'content':'1|pass'}),
            file_sha256='b'*64,manifest_sha256='c'*64)
        dependency=dict(path='/evidence/candidate/app.js',total_lines=1,pages=[page],
            file_sha256='b'*64,manifest_sha256='c'*64,native_read_evidence=False,
            execution_authorized=False,delivery_approval=False)
        result=attach_dependencies(body,[dependency])
        self.assertEqual(result['messages'][:-1],body['messages'])
        self.assertEqual(result['messages'][-1]['role'],'user')
        for bad in (dict(dependency,total_lines=101),dict(dependency,native_read_evidence=True)):
            with self.assertRaises(ValueError):attach_dependencies(body,[bad])

    def test_prepared_identity_hashes_exact_new_input_and_preserves_parent(self):
        body,parent=build(self.note,self.reads,'model',self.experiment,self.task)
        body['messages'].append({'role':'user','content':'prepared dependency input'})
        receipt=prepared_identity(body,parent)
        self.assertEqual(receipt['parent_input_sha256'],parent['input_sha256'])
        self.assertNotEqual(receipt['input_sha256'],parent['input_sha256'])
        self.assertIs(receipt['native_read_evidence'],False)
        with self.assertRaises(ValueError):prepared_identity(body,dict(parent,source_sha256='b'*64))
