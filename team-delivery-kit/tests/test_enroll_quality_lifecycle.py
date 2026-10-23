"""Pinned operator enrollment transport, not native delivery qualification."""
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from broker import quality_lifecycle_enrollment as policy
import enroll_quality_lifecycle as cli
from test_portable_contract import contract


class EnrollmentCLITests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve()
        self.spec=contract();self.ns='delivery-kit-test';self.image='sha256:'+'a'*64
        self.maintenance='10000000-0000-4000-8000-000000000005'
        self.plan=dict(version=2,policy=policy.policy.POLICY,
            run_id='10000000-0000-4000-8000-000000000001',
            issue_id='10000000-0000-4000-8000-000000000002',
            author='10000000-0000-4000-8000-000000000003',
            reviewer='10000000-0000-4000-8000-000000000004',
            base_sha='b'*40,contract_sha256=policy.policy.digest(self.spec),criteria=['A01'],
            baseline_tests={'tests/test_old.py':'c'*64},new_tests=['tests/test_new.py'],
            product_files=['app.py'],protected_files=['AGENTS.md','tests/test_old.py','tests/test_new.py'],
            criterion_tests={'A01':[dict(path='tests/test_new.py',method='test_new')]})
        self.payload=dict(plan=self.plan,contract=self.spec,maintenance_operation=self.maintenance)
        self.path=self.root/'payload.json';self.path.write_text(json.dumps(self.payload));self.path.chmod(0o600)
        self.pin=hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.calls=[];self.enabled=False;self.timeout=False;self.replace=False
        self.receipt=dict(operation='quality_lifecycle_enrollment_v2',namespace=self.ns,
            **{k:self.plan[k] for k in ('run_id','issue_id','base_sha','author','reviewer','contract_sha256')},
            plan_sha256=policy.policy.digest(self.plan),repository=self.spec['repository'],
            maintenance_operation=self.maintenance,stage='enrolled_pending_adapter',
            execution_authorized=False,merge_authorized=False,delivery_approval=False,baseline_bytes_verified=False)
        self.authority=SimpleNamespace(identity='d'*64,about=lambda:dict(namespace=self.ns,maintenance=True,
            v2_enabled=self.enabled,implementation_enabled=False),
            inspect_controller=lambda:'e'*64 if self.replace else 'd'*64)
        self.fx=SimpleNamespace(authority=lambda *a:self.authority,
            idle=lambda *a:(dict(operation_id=self.maintenance),{}),invoke=self.invoke)

    def invoke(self,identity,payload,observe):
        self.calls.append((identity,payload,observe))
        if self.timeout:raise subprocess.TimeoutExpired('fixed program',120)
        return SimpleNamespace(returncode=0,stdout=json.dumps(dict(stage='enrolled' if self.receipt else 'not_observed',
            receipt=self.receipt,delivery_approval=False)))

    def run_cli(self,**kwargs):return cli.run(self.ns,self.image,self.path,self.pin,effects=self.fx,**kwargs)

    def test_exact_enrollment_has_no_execution_or_approval(self):
        result=self.run_cli()
        self.assertEqual(result['receipt'],self.receipt);self.assertEqual(result['model_calls'],0)
        self.assertEqual(self.calls,[(self.authority.identity,self.payload,False)])

    def test_observe_never_creates_missing_enrollment(self):
        self.receipt=None
        self.assertEqual(self.run_cli(observe=True)['stage'],'not_observed')
        self.assertTrue(self.calls[0][2])
        with self.assertRaises(ValueError):self.run_cli()

    def test_pin_permissions_duplicate_keys_and_nonfinite_data_block_before_effect(self):
        self.pin='0'*64
        with self.assertRaises(ValueError):self.run_cli()
        self.pin=hashlib.sha256(self.path.read_bytes()).hexdigest();self.path.chmod(0o644)
        with self.assertRaises(ValueError):self.run_cli()
        self.path.chmod(0o600)
        for raw in (b'{"plan":{},"plan":{}}',b'{"plan":NaN}'):
            self.path.write_bytes(raw);self.pin=hashlib.sha256(raw).hexdigest()
            with self.assertRaises(ValueError):self.run_cli()
        self.assertEqual(self.calls,[])

    def test_enabled_controller_cannot_enroll(self):
        self.enabled=True
        with self.assertRaises(ValueError):self.run_cli()
        self.assertEqual(self.calls,[])

    def test_observation_does_not_require_or_enter_maintenance_after_activation(self):
        self.enabled=True
        def forbidden(*args):raise AssertionError('read-only status must not drain work')
        self.fx.idle=forbidden
        self.assertEqual(self.run_cli(observe=True)['stage'],'enrolled')
        self.assertTrue(self.calls[0][2])

    def test_timeout_is_observation_not_new_attempt_or_success(self):
        self.timeout=True
        result=self.run_cli()
        self.assertEqual(result['stage'],'observation_timeout')
        self.assertFalse(result['delivery_approval']);self.assertEqual(len(self.calls),1)

    def test_replacement_or_wrong_receipt_cannot_claim_enrolled(self):
        self.replace=True
        with self.assertRaises(ValueError):self.run_cli()
        self.replace=False;self.receipt['base_sha']='f'*40
        with self.assertRaises(ValueError):self.run_cli()


if __name__=='__main__':unittest.main()
