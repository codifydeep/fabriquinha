import copy
import unittest

from generic_calibration_input_probe import run
from generic_harness_calibration import digest
import test_generic_harness_calibration as samples


class InputProbeTests(unittest.TestCase):
    def setUp(self):
        self.fixture=samples.GenericCalibrationTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.previous=self.fixture.candidate.parent/'previous';self.previous.mkdir()
        path='tests/test_contract.py'
        self.previous_sha,_=self.fixture.snapshot(self.previous,{path:(self.fixture.candidate/path).read_text()})

    def probe(self,policy=None):
        policy=policy or self.fixture.policy
        return run(self.fixture.candidate,self.previous,self.fixture.controls,policy,digest(policy),self.previous_sha)

    def test_extracts_exact_prior_methods_and_hashes_without_executing_tests(self):
        receipt=self.probe()
        self.assertEqual(receipt['previous_methods'],self.fixture.policy['previous_methods'])
        self.assertEqual(receipt['candidate_test_sha256'],self.fixture.policy['test_sha256'])
        self.assertIs(receipt['tests_executed'],False)
        self.assertIs(receipt['delivery_approval'],False)

    def test_declared_inventory_cannot_replace_real_previous_methods(self):
        policy=copy.deepcopy(self.fixture.policy)
        policy['previous_methods']['tests/test_contract.py']['ContractTests']=['test_fabricated']
        policy['modules'][0]['classes']['ContractTests'].append('test_fabricated')
        with self.assertRaises(ValueError):self.probe(policy)

    def test_candidate_classes_or_control_inventory_cannot_drift(self):
        for mutate in (lambda p:p['modules'][0]['classes']['ContractTests'].append('test_fabricated'),
                       lambda p:p['modules'][0].update(positive_fixture='absent.txt')):
            policy=copy.deepcopy(self.fixture.policy);mutate(policy)
            with self.assertRaises(ValueError):self.probe(policy)

    def test_approved_method_order_is_preserved_after_ast_inventory_equality(self):
        path='tests/test_contract.py';source=(self.fixture.candidate/path).read_text()
        source+=' def test_another(self):\n  self.assertEqual(PRODUCT_PATH.read_text(),"correct")\n'
        manifest,files=self.fixture.snapshot(self.fixture.candidate,{path:source,'app/value.txt':'broken'})
        self.previous_sha,_=self.fixture.snapshot(self.previous,{path:source})
        policy=self.fixture.policy
        policy['candidate_manifest_sha256']=manifest;policy['test_sha256'][path]=files[path]['sha256']
        policy['previous_methods'][path]['ContractTests']=['test_existing_behavior','test_another']
        policy['modules'][0]['classes']['ContractTests']=['test_existing_behavior','test_another']
        self.assertEqual(self.probe()['previous_methods'],policy['previous_methods'])
