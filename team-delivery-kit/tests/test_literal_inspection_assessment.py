import copy
import unittest
from literal_inspection_assessment import assess


class WitnessAssessmentTests(unittest.TestCase):
    def setUp(self):
        self.cfg={'counterexample':{'facts':{'assertion_bindings':dict(initial_expected=1,poll_minimum=3,stale_expected='Newest matching: #11')}}}
        self.result=dict(stale_witness_selectivity_passed=False,reports={
            'guarded':dict(initial_requests=1,poll_requests=2,stale_guard_text='Newest matching: #11'),
            'unguarded':dict(initial_requests=1,poll_requests=2,stale_guard_text='Newest matching: #4')})

    def test_preserved_ordering_is_not_misclassified_when_only_poll_count_fails(self):
        before=copy.deepcopy(self.result);facts=assess(self.cfg,self.result)
        self.assertTrue(facts['stale_ordering_passed']);self.assertTrue(facts['initial_requests_passed'])
        self.assertFalse(facts['poll_requests_passed']);self.assertFalse(facts['all_protocol_checks_passed'])
        self.assertEqual(facts['minimum_poll_requests'],3)
        self.assertFalse(facts['delivery_approval']);self.assertFalse(facts['functional_red'])
        self.assertEqual(self.result,before)

    def test_only_meeting_all_original_conditions_passes_the_aggregate(self):
        for report in self.result['reports'].values():report['poll_requests']=3
        self.result['stale_witness_selectivity_passed']=True
        self.assertTrue(assess(self.cfg,self.result)['all_protocol_checks_passed'])
        self.result['reports']['guarded']['stale_guard_text']='Newest matching: #4'
        self.result['stale_witness_selectivity_passed']=False
        facts=assess(self.cfg,self.result)
        self.assertTrue(facts['poll_requests_passed']);self.assertFalse(facts['stale_ordering_passed'])

    def test_measurements_cannot_relabel_a_failed_gate_as_success(self):
        self.result['stale_witness_selectivity_passed']=True
        with self.assertRaises(ValueError):assess(self.cfg,self.result)
        self.result['stale_witness_selectivity_passed']='false'
        with self.assertRaises(ValueError):assess(self.cfg,self.result)

    def test_original_assertion_binding_is_used_instead_of_a_fixed_hardcoded_limit(self):
        for report in self.result['reports'].values():report['poll_requests']=3
        self.cfg['counterexample']['facts']['assertion_bindings']['poll_minimum']=4
        facts=assess(self.cfg,self.result)
        self.assertFalse(facts['poll_requests_passed']);self.assertEqual(facts['minimum_poll_requests'],4)

    def test_missing_witness_or_non_integer_observation_is_rejected(self):
        self.result['reports']['guarded']['poll_requests']=True
        with self.assertRaises(ValueError):assess(self.cfg,self.result)
        del self.result['reports']['unguarded']
        with self.assertRaises(ValueError):assess(self.cfg,self.result)
