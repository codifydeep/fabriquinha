import json
import unittest
import assess_u3_deployment as qa


class DeploymentAssessmentTests(unittest.TestCase):
    def config(self):
        return {'assessor':qa.ASSESSOR,'source_task':qa.SOURCE,'evidence_sha256':'a'*64}

    def task(self):
        return dict(id='task',agent_id=qa.ASSESSOR,issue_id='issue',wakeup_id='wake',status='completed',
            result={'output':json.dumps(dict(decision='ACCEPT_EVIDENCE',evidence_sha256='a'*64,
                reason='Only supplied technical evidence is accepted.',limitations=['No independent test execution.'],
                release_homologated=False,product_admission_authorized=False,historical_tdd_red=False))})

    def test_exact_independent_execution_and_scope(self):
        c=self.config();state={'issue_id':'issue','wakeup_id':'wake'};task=self.task()
        result=qa.verdict(c,state,task)
        self.assertEqual(result['stage'],'evidence_assessment_accepted')
        self.assertFalse(result['independent_agent_qa_approval'])
        for key in ('agent_id','issue_id','wakeup_id','status'):
            with self.assertRaises(ValueError):qa.verdict(c,state,dict(task,**{key:'wrong'}))

    def test_no_release_tdd_or_test_execution_permission(self):
        for key,value in [('release_homologated',True),('historical_tdd_red',True),
                          ('product_admission_authorized',True),('evidence_sha256','b'*64),('limitations',[])]:
            t=self.task();body=json.loads(t['result']['output']);body[key]=value;t['result']['output']=json.dumps(body)
            with self.assertRaises(ValueError):qa.verdict(self.config(),{'issue_id':'issue','wakeup_id':'wake'},t)

    def test_note_is_bounded_and_does_not_invent_tool_execution(self):
        note=qa.instruction(self.config())
        self.assertLess(len(note),3500)
        self.assertIn('Do not claim to have run tests',note)
        self.assertNotIn('DELIVERY_REVIEW_START',note)

    def test_protocol_recovery_requires_exact_oversized_reason_only(self):
        task=self.task();body=json.loads(task['result']['output']);body['reason']='x'*1213
        task['result']['output']=json.dumps(body)
        state={'issue_id':'issue','wakeup_id':'wake','stage':'blocked','reason':'exact non-authorizing QA assessment required'}
        proof=qa.protocol_recovery(self.config(),state,task)
        self.assertEqual(proof['reason_chars'],1213)
        self.assertFalse(proof['approval'])
        body['release_homologated']=True;task['result']['output']=json.dumps(body)
        with self.assertRaises(ValueError):qa.protocol_recovery(self.config(),state,task)

    def test_structured_assessment_schema_binds_digest_lengths_and_false_flags(self):
        from decision_schema import apply
        body=apply({'messages':[{'role':'user','content':'DELIVERY_DEPLOYMENT_EVIDENCE_V1:'+'a'*64}],
                    'tools':[]})
        schema=body['response_format']['json_schema']['schema']['properties']
        self.assertEqual(schema['reason']['maxLength'],1200)
        self.assertEqual(schema['evidence_sha256']['enum'],['a'*64])
        self.assertEqual(schema['release_homologated']['enum'],[False])
        self.assertTrue(body['provider']['require_parameters'])

    def test_typed_recovery_is_exact_transport_incident_not_functional_failure(self):
        config=self.config();state={'issue_id':'issue','wakeup_id':'wake','stage':'blocked','protocol_recovery':{}}
        task=dict(self.task(),status='failed',result=None)
        event=dict(status=502,category='structured_decision_response_invalid',execution_id='request',
            structured_rejection_category='nonterminal_or_non_json_response',structured_format='json_schema',
            strict_schema=True,require_parameters=True,call_number=4230)
        proof=qa.transport_incident(config,state,task,'request',event)
        self.assertEqual(proof['failed_task'],'task');self.assertFalse(proof['approval'])
        for key,value in [('execution_id','wrong'),('status',200),('category','functional_failure')]:
            with self.assertRaises(ValueError):qa.transport_incident(config,state,task,'request',dict(event,**{key:value}))
        with self.assertRaises(ValueError):qa.transport_incident(config,dict(state,typed_recovery={}),task,'request',event)

    def test_canary_uses_real_adapter_and_negative_controls_without_model(self):
        proof=qa.typed_canary()
        self.assertEqual(proof['negative_controls'],3)
        self.assertEqual(proof['model_calls'],0)
        self.assertFalse(proof['release_homologated'])
