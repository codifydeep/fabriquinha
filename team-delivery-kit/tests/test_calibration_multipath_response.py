import copy
import json
import unittest
from jsonschema import Draft202012Validator

import calibration_response_contract as contract
from broker import generic_calibration_workflow as workflow
import test_generic_calibration_multipath_proposal as proposal_samples
import test_generic_calibration_workflow as workflow_samples
import test_generic_calibration_proposal_collector as collector_samples
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import patch
from generic_harness_calibration import digest
from test_calibration_response_contract import receipt


class MultiPathResponseTests(unittest.TestCase):
    def test_selected_schema_accepts_only_selected_engine_and_shape(self):
        sample=proposal_samples.MultiPathProposalTests();sample.setUp();self.addCleanup(sample.doCleanups)
        value=contract.context('bundle',['/evidence/candidate/tests/test_ui.py'],'a'*64,
            engine='unittest_path_fixtures_v2')
        selected=Draft202012Validator(contract.schema(value))
        self.assertTrue(selected.is_valid(sample.body))
        legacy=contract.context('bundle',value['required_paths'],'a'*64)
        self.assertFalse(Draft202012Validator(contract.schema(legacy)).is_valid(sample.body))
        body=copy.deepcopy(sample.body);body['engine']='unittest_path_fixture_v1'
        self.assertFalse(selected.is_valid(body))
        request=dict(messages=[dict(role='user',content=contract.capsule(value))]+receipt(value['required_paths'][0]),
            tools=[dict(type='function',function=dict(name='read_file',parameters={}))])
        contract.apply(request)
        reply=lambda artifact:json.dumps(dict(choices=[dict(finish_reason='stop',
            message=dict(content=json.dumps(artifact)))])).encode()
        self.assertTrue(contract.validate_reply(request,reply(sample.body),'application/json'))
        with self.assertRaises(contract.CalibrationResponseRejected):
            contract.validate_reply(request,reply(body),'application/json')

    def test_capsule_engine_is_hash_bound_and_unknown_engine_rejected(self):
        value=contract.context('bundle',['/evidence/candidate/tests/test_ui.py'],'a'*64,
            engine='unittest_path_fixtures_v2')
        note=contract.capsule(value)
        self.assertEqual(contract.request({'messages':[{'role':'user','content':note}]})['engine'],
            'unittest_path_fixtures_v2')
        with self.assertRaises(ValueError):contract.request({'messages':[{'role':'user',
            'content':note.replace('unittest_path_fixtures_v2','unittest_path_fixture_v1')}]})
        with self.assertRaises(ValueError):contract.context('bundle',value['required_paths'],'a'*64,engine='shell')

    def test_persisted_selection_controls_instruction_and_cannot_change_in_flight(self):
        fixture=workflow_samples.WorkflowTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        old=workflow.instruction(fixture.config)
        self.assertNotIn('engine',contract.request({'messages':[{'role':'user','content':old}]}))
        config={**fixture.config,'calibration_engine':'unittest_path_fixtures_v2'}
        note=workflow.instruction(config)
        context=contract.request({'messages':[{'role':'user','content':note}]})
        self.assertEqual(context['engine'],config['calibration_engine'])
        self.assertIn('replacements',note);self.assertIn('fixtures',note)
        with self.assertRaises(ValueError):workflow.advance(fixture.con,config,fixture.fx,now=1)
        self.assertEqual(fixture.events,[])

    def test_native_collector_requires_persisted_selection_and_exact_waiting_wakeup(self):
        from broker import generic_calibration_proposal as proposal
        from broker import remediation_runtime_guard as guard,remediation_admission as admission,technical_remediation_plan as plans
        fixture=collector_samples.ProposalCollectorTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        body=copy.deepcopy(fixture.fixture.body);body['engine']='unittest_path_fixtures_v2'
        for m in body['modules']:
            m['fixtures']=[dict(attribute=m.pop('fixture_attribute'),product_path=m.pop('product_path'),
                positive_fixture=m.pop('positive_fixture'))]
        for n in body['negatives']:
            n['replacements']=[dict(attribute=body['modules'][0]['fixtures'][0]['attribute'],fixture=n.pop('fixture'))]
        fixture.task['result']['output']=json.dumps(body)
        workflow.initialize(fixture.con)
        selected=dict(calibration_engine=body['engine'],execution_sha256=digest(fixture.value),
            prepared=fixture.fixture.prepared,cto='cto',reviewer='lead',issue_id='issue',author_task='author-task')
        state=dict(stage='await_bundle',wakeup_id='wake')
        def collect():
            with ExitStack() as stack:
                stack.enter_context(patch.object(guard,'qualified',return_value=fixture.value))
                stack.enter_context(patch.object(admission,'Effects',return_value=SimpleNamespace(plan=lambda source:(
                    dict(cto='cto',reviewer='lead',original_author='author'),dict(plan_sha256=fixture.value['plan_sha256'])))))
                stack.enter_context(patch.object(plans,'Effects',return_value=fixture.fx))
                return proposal.collect(fixture.b,'issue','author-task','cto-task','wake',expected_engine=body['engine'])
        with self.assertRaises(ValueError):collect()
        fixture.con.execute('INSERT INTO generic_calibration_workflows VALUES(?,?,?,?)',
            ('issue','author-task',json.dumps(selected),json.dumps(state)))
        self.assertEqual(collect()['policy']['engine'],body['engine'])
        for change in (dict(stage='blocked'),dict(wakeup_id='stale')):
            fixture.con.execute('UPDATE generic_calibration_workflows SET state=?',(json.dumps({**state,**change}),))
            with self.assertRaises(ValueError):collect()
