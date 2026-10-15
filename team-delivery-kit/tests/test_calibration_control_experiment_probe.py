import copy
import unittest
import test_generic_harness_calibration_v2 as fixtures
from generic_harness_calibration import digest
import calibration_control_experiment_probe as probe
from broker import generic_calibration_proposal as proposal


class ControlExperimentProbeTests(unittest.TestCase):
    def setUp(self):
        f=fixtures.MultiPathCalibrationTests();f.setUp();self.addCleanup(f.doCleanups);self.f=f
        self.bundle=dict(operation='generic_calibration_proposal_bundle_v1',policy=f.policy,policy_sha256=digest(f.policy),
            controls=f.control_files,controls_manifest=proposal.manifest(f.control_files),execution_authorized=False,delivery_approval=False)
        self.c=dict(prepared=dict(manifest_sha256=f.policy['candidate_manifest_sha256'],test_sha256=f.policy['test_sha256']),
            test_files=list(f.policy['test_sha256']))

    def test_full_positive_and_negative_experiment_is_still_not_a_delivery_approval(self):
        before={p:p.read_bytes() for p in self.f.candidate.rglob('*') if p.is_file()}
        result=probe.run(self.f.candidate,self.bundle,digest(self.bundle))
        probe.validate(result,self.c,self.bundle)
        self.assertTrue(result['functional_controls_passed']);self.assertEqual(result['measurements']['positive']['tests'],2)
        self.assertEqual(result['measurements']['status'],'observed')
        for key in ('calibration_approved','red_approved','product_green','author_retry_authorized','execution_authorized','delivery_approval'):
            self.assertIs(result[key],False)
        self.assertEqual(before,{p:p.read_bytes() for p in self.f.candidate.rglob('*') if p.is_file()})

    def test_failed_positive_control_is_preserved_not_promoted_to_success(self):
        self.bundle['controls']={**self.f.control_files,'js-positive.js':'script-broken'}
        self.bundle['controls_manifest']=proposal.manifest(self.bundle['controls'])
        import hashlib
        self.bundle['policy']=copy.deepcopy(self.f.policy)
        self.bundle['policy']['controls_manifest_sha256']=hashlib.sha256(self.bundle['controls_manifest'].encode()).hexdigest()
        self.bundle['policy_sha256']=digest(self.bundle['policy'])
        result=probe.run(self.f.candidate,self.bundle,digest(self.bundle));probe.validate(result,self.c,self.bundle)
        self.assertFalse(result['functional_controls_passed']);self.assertGreater(result['measurements']['positive']['failures'],0)
        with self.assertRaises(ValueError):probe.validate({**result,'functional_controls_passed':True},self.c,self.bundle)

    def test_changed_bundle_or_approval_flags_cannot_be_accepted(self):
        with self.assertRaises(ValueError):probe.run(self.f.candidate,self.bundle,'c'*64)
        result=probe.run(self.f.candidate,self.bundle,digest(self.bundle))
        for key in ('execution_authorized','delivery_approval','calibration_approved'):
            with self.assertRaises(ValueError):probe.validate({**result,key:True},self.c,self.bundle)

    def test_a_negative_that_only_breaks_setup_does_not_prove_a_behavior_assertion(self):
        import hashlib
        path=self.f.candidate/'tests/test_ui.py';source=path.read_text().replace('class ContractTests(unittest.TestCase):',
            'class ContractTests(unittest.TestCase):\n def setUp(self):\n  if APP_JS.read_text()=="script-broken":self.fail("broken setup")')
        manifest,files=self.f.snapshot(self.f.candidate,{'tests/test_ui.py':source,'app/app.js':'script-broken','app/index.html':'markup-broken'})
        p=copy.deepcopy(self.f.policy);p.update(candidate_manifest_sha256=manifest,test_sha256={'tests/test_ui.py':files['tests/test_ui.py']['sha256']})
        self.bundle.update(policy=p,policy_sha256=digest(p));self.c['prepared'].update(manifest_sha256=manifest,test_sha256=p['test_sha256'])
        result=probe.run(self.f.candidate,self.bundle,digest(self.bundle));probe.validate(result,self.c,self.bundle)
        self.assertEqual(result['measurements']['negative_controls']['script']['failures'],1)
        self.assertFalse(result['functional_controls_passed']);self.assertEqual(result['negative_failure_phases']['script'],'set_up')
