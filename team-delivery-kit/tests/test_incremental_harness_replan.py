import copy
import unittest
from broker import incremental_harness_replan as replan
from broker.harness_selector_spike import TEST,TEST_SHA
from broker.test_revision_review import review_reason
import test_harness_selector_spike as fixtures


class HarnessReplanTests(unittest.TestCase):
    def setUp(self):
        fixture=fixtures.SelectorExperimentTests();fixture.setUp()
        self.proof=dict(operation='actual_node_attribute_selector_spike_v1',
            conclusion='harness_lacks_attribute_selector_support_confirmed_by_controls',
            repository_modified=False,delivery_approval=False,manifest_sha256='a'*64,
            input_sha256={TEST:TEST_SHA},reports=fixture.reports)

    def test_same_test_complete_experiment_required_not_approval(self):
        self.assertIsNone(replan.validate_experiment(self.proof,{TEST:TEST_SHA}))
        for key,value in [('delivery_approval',True),('repository_modified',True),('operation','invented')]:
            with self.assertRaises(ValueError):replan.validate_experiment({**self.proof,key:value},{TEST:TEST_SHA})
        with self.assertRaises(ValueError):replan.validate_experiment(self.proof,{TEST:'b'*64})
        wrong=copy.deepcopy(self.proof);wrong['reports']['adapted_wrong_type_control']['total_search']=1
        with self.assertRaises(ValueError):replan.validate_experiment(wrong,{TEST:TEST_SHA})

    def test_native_instruction_is_bounded_and_proposes_only_test_revision(self):
        config=dict(experiment=self.proof,experiment_sha256='b'*64)
        note=replan.instruction(config)
        self.assertLess(len(note),3800)
        self.assertIn('Baseline tests immutable',note)
        self.assertIn('No approval, merge or deploy',note)
        self.assertIn('removing CSS quotes alone does not fix',note)

    def test_independent_review_context_requires_real_delta_and_negative_controls(self):
        config=dict(cto_decision='cto-task',old_red={'red':{'test_sha256':{TEST:TEST_SHA}}})
        data=dict(harness_selector_experiment=self.proof,test_revision_proposal={'decision_task':'cto-task'})
        reason=review_reason(config,data)
        self.assertIn('unchanged copy is NOT a repair',reason)
        self.assertIn('negative controls',reason)
        self.assertIn('NOT your review execution',reason)
        with self.assertRaises(ValueError):review_reason({**config,'cto_decision':'stale'},data)
