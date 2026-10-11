import copy
import unittest

from generic_harness_calibration import digest
from calibration_policy_adapter import validate_policy,validate_receipt,product_paths,fixture_paths,input_operation,executor
from generic_calibration_input_probe import run
import test_generic_harness_calibration_v2 as multipath_samples
import test_generic_harness_calibration as legacy_samples


class PolicyAdapterTests(unittest.TestCase):
    def setUp(self):
        self.sample=multipath_samples.MultiPathCalibrationTests();self.sample.setUp()
        self.addCleanup(self.sample.doCleanups)
        self.p=self.sample.policy

    def test_exact_version_selects_fixed_executor_and_all_dependencies(self):
        validate_policy(self.p,digest(self.p))
        self.assertEqual(executor(self.p),'/generic_harness_calibration_v2.py')
        self.assertEqual(product_paths(self.p),{'app/app.js','app/index.html'})
        self.assertEqual(fixture_paths(self.p),set(self.sample.control_files))
        self.assertEqual(input_operation(self.p),'generic_calibration_inputs_v2')

    def test_unknown_or_mixed_versions_never_fall_back(self):
        for change in ({'version':'unknown'},{'engine':'unittest_path_fixture_v1'},
                       {'engine':'/bin/sh'},{'version':'generic_harness_calibration_v1'}):
            p=copy.deepcopy(self.p);p.update(change)
            with self.assertRaises(ValueError):validate_policy(p,digest(p))
            with self.assertRaises(ValueError):executor(p)

    def test_receipts_cannot_cross_versions(self):
        from generic_harness_calibration_v2 import run as execute
        receipt=execute(self.sample.candidate,self.sample.controls,self.p,digest(self.p))
        validate_receipt(receipt,self.p,digest(self.p))
        receipt['operation']='generic_harness_calibration_v1'
        with self.assertRaises(ValueError):validate_receipt(receipt,self.p,digest(self.p))

    def test_legacy_policy_retains_legacy_receipt_and_executor(self):
        sample=legacy_samples.GenericCalibrationTests();sample.setUp();self.addCleanup(sample.doCleanups)
        p=sample.policy
        self.assertEqual(validate_policy(p,digest(p)),p)
        self.assertEqual(executor(p),'/generic_harness_calibration.py')
        self.assertEqual(input_operation(p),'generic_calibration_inputs_v1')
        self.assertEqual(product_paths(p),{m['product_path'] for m in p['modules']})
        self.assertEqual(fixture_paths(p),{m['positive_fixture'] for m in p['modules']}
            |{n['fixture'] for n in p['negatives']})

    def test_read_only_probe_binds_every_product_without_executing_tests(self):
        previous=self.sample.candidate.parent/'previous';previous.mkdir()
        path='tests/test_ui.py'
        manifest,_=self.sample.snapshot(previous,{path:(self.sample.candidate/path).read_text()})
        before={f:f.read_bytes() for f in self.sample.candidate.rglob('*') if f.is_file()}
        proof=run(self.sample.candidate,previous,self.sample.controls,self.p,digest(self.p),manifest)
        self.assertEqual(proof['operation'],'generic_calibration_inputs_v2')
        self.assertEqual(set(proof['product_sha256']),product_paths(self.p))
        self.assertIs(proof['tests_executed'],False)
        self.assertIs(proof['execution_authorized'],False)
        self.assertEqual(before,{f:f.read_bytes() for f in self.sample.candidate.rglob('*') if f.is_file()})
