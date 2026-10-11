import unittest
from broker import generic_calibration_workflow as workflow
from calibration_response_contract import context,capsule


class CalibrationPromptBindingTests(unittest.TestCase):
    def setUp(self):
        self.c=dict(issue_id='issue',cto='cto',reviewer='lead',test_files=['tests/test_one.py'],criteria={'A01':'preserved'})
        self.task=dict(agent_id='cto',issue_id='issue',wakeup_id='wake')

    def test_bundle_capsule_is_bound_to_exact_controller_phase_actor_and_wakeup(self):
        note=workflow.instruction(self.c)
        result=workflow.bound_prompt(self.c,{'stage':'await_bundle','wakeup_id':'wake'},self.task,
            'DELIVERY_PLANNING_START marker\nSource: source\n'+note,note)
        self.assertEqual(result['phase'],'bundle')

    def test_foreign_actor_issue_wakeup_or_blocked_phase_cannot_select_prompt(self):
        note=workflow.instruction(self.c);state={'stage':'await_bundle','wakeup_id':'wake'}
        for task in ({**self.task,'agent_id':'lead'},{**self.task,'issue_id':'other'},
                {**self.task,'wakeup_id':'foreign'}):
            with self.assertRaises(ValueError):workflow.bound_prompt(self.c,state,task,note,note)
        with self.assertRaises(ValueError):workflow.bound_prompt(self.c,{'stage':'blocked'},self.task,note,note)

    def test_capsule_hash_and_source_cannot_be_self_declared(self):
        note=workflow.instruction(self.c);foreign=workflow.instruction({**self.c,'criteria':{'A01':'changed'}})
        with self.assertRaises(ValueError):workflow.bound_prompt(self.c,{'stage':'await_bundle','wakeup_id':'wake'},self.task,foreign,note)

    def test_attestation_and_independent_review_keep_exact_policy_control_read_scope(self):
        paths=['/evidence/candidate/tests/test_one.py','/evidence/controls/positive.txt','/evidence/policy/policy.json']
        for phase,stage,actor,field in (('attestation','policy_attestation_wait','cto','attestation_wakeup'),
                ('review','policy_review_wait','lead','policy_wakeup')):
            note=capsule(context(phase,paths,'a'*64,'b'*64,'c'*64))
            value=workflow.bound_prompt(self.c,{'stage':stage,field:'wake'},dict(self.task,agent_id=actor),note,note)
            self.assertEqual(value['required_paths'],paths)
            self.assertEqual(value['phase'],phase)
