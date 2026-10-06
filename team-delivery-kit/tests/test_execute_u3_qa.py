import unittest
import execute_u3_qa as qa


class ExecutedQATests(unittest.TestCase):
    def test_operator_script_loads_without_host_assessment_module(self):
        from pathlib import Path
        import builtins
        from unittest.mock import patch
        original=builtins.__import__
        def restricted(name,*args,**kwargs):
            if name=='assess_u3_deployment':raise ModuleNotFoundError(name)
            return original(name,*args,**kwargs)
        namespace={'__name__':'operator_fixed_qa'}
        with patch('builtins.__import__',side_effect=restricted):
            exec(compile(Path(qa.__file__).read_text(),'operator_fixed_qa','exec'),namespace)
        self.assertEqual(namespace['ASSESSOR'],qa.ASSESSOR)
        self.assertEqual(namespace['digest']({'a':1}),qa.digest({'a':1}))

    def config(self):return dict(assessor=qa.ASSESSOR,author=qa.AUTHOR,evidence_sha256='a'*64,source_sha=qa.SHA)
    def task(self):return dict(id='task',status='completed',agent_id=qa.ASSESSOR,issue_id='issue',wakeup_id='wake')
    def decision(self):return dict(operation='run_fixed_deployment_qa',evidence_sha256='a'*64,
        reason='Validate exact deployed revision.',release_homologated=False,product_admission_authorized=False)

    def test_only_independent_exact_request_can_execute_fixed_qa(self):
        proof=qa.request_receipt(self.config(),{'issue_id':'issue','wakeup_id':'wake'},self.task(),self.decision())
        self.assertEqual(proof['operation'],'run_fixed_deployment_qa')
        self.assertFalse(proof['release_homologated'])
        for key in ('agent_id','issue_id','wakeup_id','status'):
            with self.assertRaises(ValueError):qa.request_receipt(self.config(),{'issue_id':'issue','wakeup_id':'wake'},
                dict(self.task(),**{key:'wrong'}),self.decision())

    def test_no_agent_command_url_image_or_authority_override(self):
        for key,value in [('command','rm anything'),('url','https://example.com'),('image','latest'),
                          ('release_homologated',True),('evidence_sha256','b'*64),('operation','deploy')]:
            with self.assertRaises(ValueError):qa.request_receipt(self.config(),{'issue_id':'issue','wakeup_id':'wake'},
                self.task(),dict(self.decision(),**{key:value}))

    def test_no_blind_retry_after_validation_intent_or_failure(self):
        for stage in ('validation_intent','blocked','validation_passed'):
            self.assertFalse(qa.may_validate({'stage':stage}))
        self.assertTrue(qa.may_validate({'stage':'validation_requested'}))

    def test_real_typed_request_canary_has_no_model_or_execution(self):
        proof=qa.request_canary()
        self.assertEqual(proof['negative_controls'],3)
        self.assertEqual(proof['model_calls'],0)
        self.assertFalse(proof['worker_tool_executed'])

    def test_padding_recovery_requires_exact_native_incident_and_is_one_shot(self):
        state=dict(stage='blocked',issue_id='issue',wakeup_id='wake')
        task=dict(self.task(),status='failed')
        rejection=dict(operation='rejected_typed_decision_adapter_v1',category='typed_mixed_content',
            worker_tool_executed=False,delivery_approval=False,response_shape=dict(parsed=True,terminal=True,
            expected_tool=True,arguments_json_valid=True,arguments_schema_valid=True,
            legacy_function_call=False,submissions=1,content_shape='whitespace_only',content_chars=1))
        proof=qa.padding_incident(state,task,'request',rejection)
        self.assertFalse(proof['approval'])
        with self.assertRaises(ValueError):qa.padding_incident(dict(state,padding_recovery=proof),task,'request',rejection)
        for change in ({'content_shape':'nonempty'},{'arguments_schema_valid':False},{'content_chars':2}):
            with self.assertRaises(ValueError):qa.padding_incident(state,task,'request',
                dict(rejection,response_shape=dict(rejection['response_shape'],**change)))

    def test_validation_padding_is_bounded_ascii_only_and_preserves_arguments(self):
        import json
        from decision_schema import apply as schema
        import typed_decision_contract as typed
        from structured_response_contract import StructuredResponseRejected
        body=typed.apply(schema({'messages':[{'role':'user','content':
            'DELIVERY_DEPLOYMENT_VALIDATION_V1:'+'a'*64+'\nDELIVERY_TYPED_DEPLOYMENT_VALIDATION_V1:'+'a'*64}],'tools':[]}))
        value=self.decision()
        def wire(content):return json.dumps({'choices':[{'finish_reason':'tool_calls','message':{
            'content':content,'tool_calls':[{'type':'function','function':{
            'name':'submit_deployment_validation_request','arguments':json.dumps(value)}}]}}]}).encode()
        for content in (' ','\t\r\n',' '*16):
            normalized,receipt=typed.normalize_validation_padding(body,wire(content),'application/json')
            self.assertTrue(receipt['model_arguments_unchanged'])
            result,_,proof=typed.translate(body,normalized,'application/json')
            self.assertEqual(json.loads(json.loads(result)['choices'][0]['message']['content']),value)
            self.assertFalse(proof['worker_tool_executed'])
        for content in ('prose',' '*17,'\u00a0'):
            normalized,receipt=typed.normalize_validation_padding(body,wire(content),'application/json')
            self.assertIsNone(receipt)
            with self.assertRaises(StructuredResponseRejected):typed.translate(body,normalized,'application/json')

    def test_passing_receipt_requires_new_execution_same_source_and_all_checks(self):
        checks=['check'+str(n) for n in range(40)]
        browser={'status':'passed','cleanup':'passed','automated':True,'result':{
            'status':'passed','source_sha':qa.SHA,'contexts':2,'checks':checks},
            'identity':{'source_sha':qa.SHA,'application_image':'image'},'screenshot_sha256':'b'*64}
        deployment={'source_sha':qa.SHA,'image':'image','browser_checks':checks}
        proof=qa.executed_receipt({'task_id':'task'},deployment,browser,['/health','/ready','/','/static/app.js','/static/style.css'])
        self.assertFalse(proof['release_homologated']);self.assertFalse(proof['independent_agent_qa_approval'])
        for change in ({'cleanup':'failed'},{'status':'failed'}):
            with self.assertRaises(ValueError):qa.executed_receipt({'task_id':'task'},deployment,dict(browser,**change),['x']*5)
