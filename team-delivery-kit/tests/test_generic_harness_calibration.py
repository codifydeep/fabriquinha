import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from generic_harness_calibration import run, validate_policy, validate_receipt, digest


class GenericCalibrationTests(unittest.TestCase):
    def snapshot(self, root, files):
        for name, text in files.items():
            path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text)
        inventory={name:{'bytes':(root/name).stat().st_size,
            'sha256':hashlib.sha256((root/name).read_bytes()).hexdigest()} for name in files}
        raw=json.dumps({'files':inventory},sort_keys=True).encode()
        (root/'manifest.json').write_bytes(raw)
        return hashlib.sha256(raw).hexdigest(),inventory

    def setUp(self):
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        root=Path(directory.name);self.candidate=root/'candidate';self.controls=root/'controls'
        self.candidate.mkdir();self.controls.mkdir()
        test=('import unittest\nfrom pathlib import Path\n'
            'PRODUCT_PATH=Path(__file__).parents[1]/"app/value.txt"\n'
            'class ContractTests(unittest.TestCase):\n'
            ' def test_existing_behavior(self):\n'
            '  value=PRODUCT_PATH.read_text()\n'
            '  if value=="runtime_error": raise RuntimeError("not a regression assertion")\n'
            '  if value=="skip": self.skipTest("not a regression assertion")\n'
            '  self.assertEqual(value,"correct")\n')
        manifest,files=self.snapshot(self.candidate,{'tests/test_contract.py':test,'app/value.txt':'broken'})
        controls,_=self.snapshot(self.controls,{'positive.txt':'correct','negative.txt':'broken'})
        self.policy=dict(version='generic_harness_calibration_v1',engine='unittest_path_fixture_v1',
            source_task='01a12370-34e8-7a3a-93f8-e8baec192a8e',execution_sha256='a'*64,plan_sha256='b'*64,
            candidate_manifest_sha256=manifest,controls_manifest_sha256=controls,criteria=['A01'],
            test_sha256={'tests/test_contract.py':files['tests/test_contract.py']['sha256']},
            previous_methods={'tests/test_contract.py':{'ContractTests':['test_existing_behavior']}},
            modules=[dict(path='tests/test_contract.py',fixture_attribute='PRODUCT_PATH',
                product_path='app/value.txt',positive_fixture='positive.txt',
                classes={'ContractTests':['test_existing_behavior']})],
            negatives=[dict(id='regression',module='tests/test_contract.py',class_name='ContractTests',
                method='test_existing_behavior',fixture='negative.txt',criteria=['A01'])])

    def test_real_positive_and_assertion_negative_are_not_product_green(self):
        before=(self.candidate/'app/value.txt').read_bytes()
        receipt=run(self.candidate,self.controls,self.policy,digest(self.policy))
        self.assertEqual(receipt['positive']['tests'],1)
        self.assertEqual(receipt['negative_controls']['regression']['failures'],1)
        self.assertEqual(receipt['policy_sha256'],digest(self.policy))
        for field in ('product_green','red_approved','delivery_approval'):
            self.assertIs(receipt[field],False)
        self.assertEqual((self.candidate/'app/value.txt').read_bytes(),before)

    def test_reject_stale_policy_missing_criteria_or_weakened_discovery(self):
        for mutate in (lambda p:p.update(engine='arbitrary_shell'),
                       lambda p:p['negatives'][0].update(criteria=[]),
                       lambda p:p['modules'][0].update(classes={'ContractTests':['test_other']}),
                       lambda p:p['modules'][0].update(path='../escape'),
                       lambda p:p.update(test_sha256={'tests/test_contract.py':'c'*64})):
            bad=copy.deepcopy(self.policy);mutate(bad)
            with self.assertRaises(ValueError):run(self.candidate,self.controls,bad,digest(bad))
        with self.assertRaises(ValueError):run(self.candidate,self.controls,self.policy,'0'*64)

    def test_negative_must_fail_by_assertion_not_error_or_skip(self):
        for contents in ('correct','runtime_error','skip'):
            controls,_=self.snapshot(self.controls,{'positive.txt':'correct','negative.txt':contents})
            p=copy.deepcopy(self.policy);p['controls_manifest_sha256']=controls
            with self.assertRaises(ValueError):run(self.candidate,self.controls,p,digest(p))

    def test_receipt_never_accepts_boolean_counts_partial_controls_or_authority(self):
        receipt=run(self.candidate,self.controls,self.policy,digest(self.policy))
        for mutate in (lambda r:r['positive'].update(tests=True),
                       lambda r:r.update(negative_controls={}),
                       lambda r:r.update(red_approved=True),
                       lambda r:r.update(candidate_manifest_sha256='0'*64),
                       lambda r:r['negative_controls']['regression'].update(errors=1,failures=0)):
            bad=copy.deepcopy(receipt);mutate(bad)
            with self.assertRaises(ValueError):validate_receipt(bad,self.policy,digest(self.policy))

    def test_positive_reference_must_pass_every_declared_method(self):
        controls,_=self.snapshot(self.controls,{'positive.txt':'broken','negative.txt':'broken'})
        p=copy.deepcopy(self.policy);p['controls_manifest_sha256']=controls
        with self.assertRaises(ValueError):run(self.candidate,self.controls,p,digest(p))

    def test_control_bytes_and_candidate_bytes_cannot_change_under_same_policy(self):
        for path in (self.candidate/'tests/test_contract.py',self.controls/'negative.txt'):
            original=path.read_bytes();path.write_bytes(original+b'changed')
            try:
                with self.assertRaises(ValueError):run(self.candidate,self.controls,self.policy,digest(self.policy))
            finally:path.write_bytes(original)

    def test_fixture_seam_cannot_target_a_different_product_or_missing_attribute(self):
        for field,value in (('fixture_attribute','UNKNOWN_PATH'),('product_path','tests/test_contract.py')):
            p=copy.deepcopy(self.policy);p['modules'][0][field]=value
            with self.assertRaises(ValueError):run(self.candidate,self.controls,p,digest(p))

    def test_policy_does_not_accept_commands_or_self_declared_approval(self):
        for field,value in (('command',['sh','-c','true']),('delivery_approval',True)):
            p=copy.deepcopy(self.policy);p[field]=value
            with self.assertRaises(ValueError):validate_policy(p,digest(p))

