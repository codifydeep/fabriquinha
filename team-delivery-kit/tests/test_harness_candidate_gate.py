import copy
import unittest
from broker import harness_candidate_gate as gate
from broker.harness_selector_spike import TEST,TEST_SHA
import test_incremental_harness_replan as replan_fixtures
import test_harness_candidate_probe as probe_fixtures


class HarnessGateTests(unittest.TestCase):
    def setUp(self):
        f=replan_fixtures.HarnessReplanTests();f.setUp();self.experiment=f.proof
        p=probe_fixtures.CandidateProbeTests();p.setUp()
        self.red={'red':dict(manifest_sha256='b'*64,test_sha256={TEST:'c'*64})}
        self.receipt=dict(operation='actual_candidate_selector_controls_v2',repository_modified=False,
            delivery_approval=False,candidate_manifest_sha256='b'*64,candidate_sha256={TEST:'c'*64},
            fixture_manifest_sha256='a'*64,fixture_sha256={TEST:TEST_SHA},reports=p.reports,
            internal_negatives=[dict(name=name,canonical_match=canonical,accepted=False,
                rejected_by_predicate=True) for name,canonical in [('wrong_type_text',False),
                ('wrong_type_number',False),('wrong_label',True),('blank_label',True),('inside_form',True)]])

    def test_legacy_cache_and_broken_internal_control_are_not_approval(self):
        with self.assertRaises(ValueError):gate.qualify({**self.receipt,
            'operation':'actual_candidate_selector_controls_v1'},self.red,self.experiment)
        receipt=copy.deepcopy(self.receipt);receipt['internal_negatives'][-1]['canonical_match']=False
        with self.assertRaises(ValueError):gate.qualify(receipt,self.red,self.experiment)

    def test_admission_requires_exact_snapshots_and_controls(self):
        self.assertIsNone(gate.qualify(self.receipt,self.red,self.experiment))
        for key,value in [('delivery_approval',True),('repository_modified',True),
            ('candidate_manifest_sha256','d'*64),('candidate_sha256',{TEST:TEST_SHA}),
            ('fixture_manifest_sha256','d'*64),('fixture_sha256',{TEST:'d'*64})]:
            with self.assertRaises(ValueError):gate.qualify({**self.receipt,key:value},self.red,self.experiment)

    def test_positive_only_or_false_positive_receipt_is_not_evidence(self):
        receipt=copy.deepcopy(self.receipt);receipt['reports']['wrong_type']['total_search']=1
        with self.assertRaises(ValueError):gate.qualify(receipt,self.red,self.experiment)

    def test_legacy_trial_is_not_retroactively_qualified(self):
        self.assertIsNone(gate.enforce(None,{},None))
