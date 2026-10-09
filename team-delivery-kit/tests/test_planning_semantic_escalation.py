import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from planning_semantic_escalation import qualify,advance,pending,diagnosis_prompt


class PlanningSemanticEscalationTests(unittest.TestCase):
    def fixture(self):
        state=dict(stage='blocked',active='techlead',owner='techlead',retry_techlead=1,
            configuration_sha256='a'*64,base_sha='b'*40,issues={'techlead':'second-issue'},
            rejected_task_id='first-task',
            category='ValueError:each implementation card requires a new discoverable test file',
            rejected_category='ValueError:each implementation card requires a new discoverable test file',
            outputs={'product':{'proposal':{'role':'product'}},'cto':{'proposal':{'role':'cto','stack':'Python'}}})
        runs=[dict(id=t,status='completed',agent_id='lead',issue_id=i)
              for t,i in (('first-task','first-issue'),('second-task','second-issue'))]
        bindings=[dict(task_id=r['id'],agent_id='lead',issue_id=r['issue_id'],
            mode='planning',lease_status='closed',scope='workspace:lead:planning:'+r['id']) for r in runs]
        plan=dict(role='techlead',cards=[
            dict(id='C1',owner='backend_data',depends_on=[],files=['app/server.py'],
                 test_command=['python3','-m','unittest','discover','-s','.','-q']),
            dict(id='C2',owner='frontend',depends_on=['C1'],files=['app/static/app.js'],
                 test_command=['python3','-m','unittest','discover','-s','.','-q'])],integration_order=['C1','C2'])
        return state,runs,bindings,[copy.deepcopy(plan),copy.deepcopy(plan)],['app/server.py','app/static/app.js']

    def test_repeated_exact_rejection_escalates_without_synthesizing_tests(self):
        state,runs,bindings,plans,tracked=self.fixture();original=copy.deepcopy(state)
        result=qualify(state,runs,bindings,plans,tracked,'lead')
        self.assertEqual(state,original)
        self.assertEqual(result['stage'],'planning_technical_diagnosis')
        self.assertEqual(result['owner'],'cto')
        self.assertEqual(result['retry_techlead'],1)
        proof=result['semantic_escalation']['proof']
        self.assertFalse(proof['delivery_approval']);self.assertFalse(proof['author_execution_authorized'])
        self.assertEqual(result['outputs'],state['outputs'])
        self.assertEqual(result['semantic_escalation']['rejected_plan'],plans[-1])
        self.assertEqual(result['semantic_escalation']['previous_blocker'],original)
        self.assertIsNone(qualify(result,runs,bindings,plans,tracked,'lead'))

    def test_changed_identity_active_execution_other_failure_or_valid_plan_cannot_resume(self):
        for target,key,value in [('state','category','ValueError:other'),('state','rejected_task_id','other'),
            ('run','status','running'),('run','agent_id','other'),('binding','lease_status','running'),
            ('binding','mode','implementation'),('binding','issue_id','other'),('binding','scope','implementation')]:
            state,runs,bindings,plans,tracked=self.fixture()
            {'state':state,'run':runs[-1],'binding':bindings[-1]}[target][key]=value
            with self.subTest(target=target,key=key):
                self.assertIsNone(qualify(state,runs,bindings,plans,tracked,'lead'))
        state,runs,bindings,plans,tracked=self.fixture()
        for i,card in enumerate(plans[-1]['cards']):card['files'].append('tests/test_new_'+str(i)+'.py')
        self.assertIsNone(qualify(state,runs,bindings,plans,tracked,'lead'))

    def test_technical_diagnosis_records_intent_then_requires_fresh_lead_plan(self):
        state,runs,bindings,plans,tracked=self.fixture()
        ready=qualify(state,runs,bindings,plans,tracked,'lead')
        proposal=dict(role='cto',stack='Python',components=['stdlib API','vanilla web'],security=['No secrets'],
            technical_decisions=['C1 and C2 must declare distinct new discoverable unittest paths'],risks=[])
        with tempfile.TemporaryDirectory() as directory, \
             patch('planning_intake.issue_for',return_value='diagnosis-issue') as create, \
             patch('planning_intake.completed_output',return_value=('diagnosis-task',json.dumps(proposal))):
            path=Path(directory)/'state.json'
            result=advance(ready,'CEO acceptance remains binding.','Qualified scopes',{'agents':{'cto':'cto'}},path,'TRIAL-1')
            self.assertEqual(result['stage'],'technical_replanning_techlead')
            self.assertEqual(result['semantic_escalation']['stage'],'awaiting_replan')
            self.assertEqual(result['outputs'],ready['outputs'])
            self.assertFalse(result['semantic_escalation']['diagnosis']['delivery_approval'])
            self.assertEqual(create.call_args.kwargs['run_name'],'TRIAL-1-S1')
            self.assertEqual(json.loads(path.read_text()),result)

    def test_failed_diagnosis_stays_visible_with_cto_without_identical_retry(self):
        state,runs,bindings,plans,tracked=self.fixture()
        ready=qualify(state,runs,bindings,plans,tracked,'lead')
        with tempfile.TemporaryDirectory() as directory, \
             patch('planning_intake.issue_for',return_value='diagnosis-issue'), \
             patch('planning_intake.completed_output',side_effect=RuntimeError('native terminal failure')):
            result=advance(ready,'Original brief','Scopes',{'agents':{'cto':'cto'}},Path(directory)/'state.json','TRIAL-1')
            self.assertEqual(result['stage'],'blocked');self.assertEqual(result['owner'],'cto')
            self.assertEqual(result['semantic_escalation']['stage'],'blocked')
            self.assertIsNone(qualify(result,runs,bindings,plans,tracked,'lead'))

    def test_pending_only_accepts_same_pinned_configuration(self):
        state,runs,bindings,plans,tracked=self.fixture();ready=qualify(state,runs,bindings,plans,tracked,'lead')
        self.assertTrue(pending(ready,{'configuration_sha256':'a'*64,'base_sha':'b'*40},{},None))
        self.assertFalse(pending(ready,{'configuration_sha256':'c'*64,'base_sha':'b'*40},{},None))
        self.assertFalse(pending(ready,{'configuration_sha256':'a'*64,'base_sha':'c'*40},{},None))

    def test_projection_preserves_complete_execution_declarations(self):
        state,runs,bindings,plans,tracked=self.fixture()
        ready=qualify(state,runs,bindings,plans,tracked,'lead')
        prompt=diagnosis_prompt(ready,'ORIGINAL CEO REQUEST','QUALIFIED SCOPES')
        self.assertIn('ORIGINAL CEO REQUEST',prompt)
        self.assertIn('QUALIFIED SCOPES',prompt)
        for card in plans[-1]['cards']:
            for value in card['files']+card['test_command']+[card['id'],card['owner']]:
                self.assertIn(json.dumps(value),prompt)
        self.assertIn('"integration_order":["C1","C2"]',prompt)

    def test_observation_timeout_preserves_same_diagnosis_without_retry(self):
        state,runs,bindings,plans,tracked=self.fixture()
        ready=qualify(state,runs,bindings,plans,tracked,'lead')
        with tempfile.TemporaryDirectory() as directory, \
             patch('planning_intake.issue_for',return_value='diagnosis-issue'), \
             patch('planning_intake.completed_output',side_effect=TimeoutError('observer deadline')):
            result=advance(ready,'Brief','Scopes',{'agents':{'cto':'cto'}},Path(directory)/'state.json','TRIAL-1')
            self.assertEqual(result['stage'],'planning_technical_diagnosis')
            self.assertEqual(result['semantic_escalation']['stage'],'diagnosing')
            self.assertEqual(result['semantic_escalation']['diagnosis_issue_id'],'diagnosis-issue')
            self.assertTrue(pending(result,{'configuration_sha256':'a'*64,'base_sha':'b'*40},{},None))

    def test_changed_proof_or_preserved_proposal_cannot_dispatch_diagnosis(self):
        state,runs,bindings,plans,tracked=self.fixture();ready=qualify(state,runs,bindings,plans,tracked,'lead')
        for field,value in (('configuration_sha256','c'*64),('delivery_approval',True),
                            ('author_execution_authorized',True),('proposal_sha256',['c'*64])):
            changed=copy.deepcopy(ready);changed['semantic_escalation']['proof'][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):diagnosis_prompt(changed,'Brief','Scopes')
