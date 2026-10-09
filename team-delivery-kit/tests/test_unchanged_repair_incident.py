import copy
import json
import unittest
from broker.unchanged_repair_incident import describe, advance, handle, instruction, qualify_transport_recovery


class UnchangedRepairIncidentTests(unittest.TestCase):
    def setUp(self):
        self.source='01a12276-4440-750b-b7c9-85751f424d2f'
        self.issue='01a1226c-648a-727d-a3a5-58a415526ce2'
        self.task=dict(id=self.source,issue_id=self.issue,status='completed',agent_id='author')
        self.route=dict(issue_id=self.issue,author='author',cto='cto',test_first=True,enabled=True,
                        test_first_files=['tests/test_new.py'],minimum_calls=8)
        self.incident=dict(kind='rejected_red',issue_id=self.issue,task_id=self.source,
            reason='sponsored repair requires changed NEW-test snapshot',exit_code=1,
            manifest_sha256='a'*64,test_sha256={'tests/test_new.py':'b'*64},output_sha256='c'*64)
        self.policy=dict(seed_previous_tests=True,old_red={'red':{'test_sha256':{'tests/test_new.py':'b'*64}}})

    def test_unchanged_receipt_is_diagnosis_not_retry_or_red(self):
        d=describe(self.task,self.route,self.incident,self.policy)
        self.assertFalse(d['author_retry_authorized'])
        self.assertFalse(d['red_verified'])
        self.assertEqual(d['cause'],'unknown')

    def test_diagnosis_projects_to_one_nonexecuting_typed_submission(self):
        from decision_schema import apply
        from typed_decision_contract import apply as typed
        d=describe(self.task,self.route,self.incident,self.policy)
        wire=typed(apply({'messages':[dict(role='user',content=instruction(d))],
                          'tools':[dict(type='function',function={'name':'terminal'})]}))
        self.assertEqual(len(wire['tools']),1)
        self.assertEqual(wire['tool_choice'],{'type':'function','function':{'name':'submit_delivery_decision'}})
        schema=wire['tools'][0]['function']['parameters']
        self.assertEqual(schema['properties']['action']['enum'],['escalate_cto'])
        self.assertEqual(schema['properties']['reason']['maxLength'],1200)
        self.assertIn('HARD LIMIT 1200',instruction(d))

    def test_only_exact_length_failure_qualifies_changed_transport(self):
        d=describe(self.task,self.route,self.incident,self.policy)
        state=dict(stage='technical_hold',category='diagnosis_execution_failed',task_id='diagnosis',wakeup_id='wake')
        task=dict(id='diagnosis',wakeup_id='wake',agent_id='cto',issue_id=self.issue,status='failed',
                  failure_reason='agent_error.provider_server_error')
        event=dict(status=502,category='structured_decision_response_invalid',decision_schema='delivery_decision_v1',
                   structured_rejection_category='schema_violation',structured_rejection_diagnostic=dict(
                       version='structured-constraint-v1',constraints=['maxLength'],upstream_sha256='d'*64))
        proof=qualify_transport_recovery(d,state,task,event)
        self.assertFalse(proof['author_retry_authorized']);self.assertEqual(proof['attempt_limit'],1)
        for changed in (dict(task,status='completed'),dict(task,agent_id='author'),dict(task,wakeup_id='stale')):
            with self.assertRaises(ValueError):qualify_transport_recovery(d,state,changed,event)
        with self.assertRaises(ValueError):qualify_transport_recovery(d,state,task,dict(event,status=429))

    def test_overlength_recommendation_does_not_advance(self):
        class FX:
            def runs(self):return [dict(id='cto-task',wakeup_id='wake',agent_id='cto',status='completed')]
            def decision(self,task):return dict(action='escalate_cto',reason='x'*1201,optional_files=[])
        saved=[]
        advance(describe(self.task,self.route,self.incident,self.policy),
                dict(stage='awaiting_diagnosis',wakeup_id='wake'),FX(),saved.append,now=1)
        self.assertEqual(saved[-1]['category'],'diagnosis_recommendation_rejected')

    def test_unrelated_argument_incident_retains_legacy_recovery(self):
        prior=dict(stage='test_first_blocked',data=json.dumps(dict(
            error='test_first_correction_failed_after_cto_diagnosis',
            diagnostic={'kind':'rejected_forced_tool_response'})))
        self.assertFalse(handle(object(),self.route,[self.task],self.task,prior,object()))

    def test_changed_stale_failed_or_unseeded_inputs_rejected(self):
        for key,value in (('task',dict(self.task,status='failed')),
                          ('incident',dict(self.incident,test_sha256={'tests/test_new.py':'d'*64})),
                          ('incident',dict(self.incident,task_id='stale')),
                          ('policy',dict(self.policy,seed_previous_tests=False)),
                          ('route',dict(self.route,cto='author'))):
            args={k:getattr(self,k) for k in ('task','route','incident','policy')};args[key]=value
            with self.assertRaises(ValueError):describe(**args)

    def test_uncertain_post_is_only_observed_never_reposted(self):
        class FX:
            calls=[]
            def available(self):return True
            def remaining(self):return 100
            def wake(self,identity,allow_create):
                self.calls.append(allow_create)
                if allow_create:raise TimeoutError()
                return None
        fx=FX();state={};identity=describe(self.task,self.route,self.incident,self.policy)
        saved=[]
        def save(value):
            nonlocal state
            state=copy.deepcopy(value);saved.append(state)
        advance(identity,state,fx,save,now=1)
        advance(identity,state,fx,save,now=2)
        self.assertEqual(fx.calls,[True,False])
        self.assertEqual(state['stage'],'post_intent')
        self.assertFalse(state['author_retry_authorized'])

    def test_completed_cto_recommendation_cannot_dispatch_author(self):
        class FX:
            def runs(self):return [dict(id='cto-task',wakeup_id='wake',agent_id='cto',status='completed')]
            def decision(self,task):return dict(action='request_correction',reason='Investigate with a fixed experiment',optional_files=[])
        identity=describe(self.task,self.route,self.incident,self.policy);saved=[]
        advance(identity,dict(stage='awaiting_diagnosis',wakeup_id='wake'),FX(),saved.append,now=1)
        self.assertEqual(saved[-1]['stage'],'diagnosed_hold')
        self.assertFalse(saved[-1]['author_retry_authorized'])
        self.assertFalse(saved[-1]['delivery_approval'])
