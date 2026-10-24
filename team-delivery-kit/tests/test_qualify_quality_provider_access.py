"""Fixed-runtime report shape, never actual provider credit or native approval."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import qualify_quality_provider_access as driver


def report(sources):
    return dict(operation='fixed_payment_resolution_runtime_canary_v1',status='passed',
        credit_source='fixed_loopback_not_provider',fixture_http_calls=8,model_calls=0,real_provider_calls=0,
        confirmation_required=True,counter_preserved=True,zero_credit_rejected=True,unlimited_key_supported=True,
        readback_no_repeat=True,partial_finish_no_repeat=True,live_lock_observed=True,
        credential_mounts=False,docker_socket=False,image_data_tmpfs=True,
        delivery_approval=False,tests_approved=False,sources=sources)


class QualityPaymentCanaryQualificationTests(unittest.TestCase):
    def test_synthetic_controls_cannot_claim_live_credit_authority(self):
        sources={key:'a'*64 for key in driver.SOURCES};value=report(sources)
        self.assertEqual(driver.validate(value,sources),value)
        for changes in (dict(credit_source='provider'),dict(real_provider_calls=1),dict(model_calls=False),
                dict(counter_preserved=False),dict(confirmation_required=False),dict(live_lock_observed=False),
                dict(partial_finish_no_repeat=False),dict(image_data_tmpfs=False),dict(credential_mounts=True),
                dict(tests_approved=True),dict(delivery_approval=True),dict(fixture_http_calls=7),
                dict(sources={**sources,'contract':'0'*64}),dict(extra=True)):
            with self.subTest(changes=changes),self.assertRaises(ValueError):driver.validate({**value,**changes},sources)

    def test_preserved_unknown_effect_never_runs_or_deletes_a_replacement(self):
        namespace='delivery-kit-fixture';operation='60000000-0000-4000-8000-000000000001';image='sha256:'+'a'*64
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();(root/'tests').mkdir()
            for path in [*driver.SOURCES.values(),'tests/quality_provider_resolution_canary.py']:
                dest=root/path;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(path.encode())
            parent=root/'.local-fixture/backups';parent.mkdir(parents=True,mode=0o700)
            sources={key:driver.sha((root/path).read_bytes()) for key,path in driver.SOURCES.items()}
            identity=dict(namespace=namespace,image=image,operation=operation,sources=sources,
                script_sha256=driver.sha((root/'tests/quality_provider_resolution_canary.py').read_bytes()))
            archive=parent/('quality-payment-runtime-'+operation);archive.mkdir(mode=0o700)
            driver.save(archive/'state.json',dict(identity=identity,stage='execution_intent'))
            with patch.object(driver,'ROOT',root),patch.object(driver.subprocess,'run',side_effect=AssertionError('must not rerun')):
                result=driver.qualify(namespace,image,operation,observe=True)
            self.assertEqual(result['stage'],'outcome_unknown');self.assertFalse(result['delivery_approval'])
            self.assertEqual(json.loads(driver.read(archive/'state.json'))['stage'],'execution_intent')

    def test_success_output_resumes_missing_final_receipt_without_new_docker_effect(self):
        namespace='delivery-kit-fixture';operation='60000000-0000-4000-8000-000000000001';image='sha256:'+'a'*64
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();(root/'tests').mkdir()
            for path in [*driver.SOURCES.values(),'tests/quality_provider_resolution_canary.py']:
                dest=root/path;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(path.encode())
            parent=root/'.local-fixture/backups';parent.mkdir(parents=True,mode=0o700)
            sources={key:driver.sha((root/path).read_bytes()) for key,path in driver.SOURCES.items()}
            identity=dict(namespace=namespace,image=image,operation=operation,sources=sources,
                script_sha256=driver.sha((root/'tests/quality_provider_resolution_canary.py').read_bytes()))
            held=dict(operation_id='held',stage='sealed',drained=True)
            archive=parent/('quality-payment-runtime-'+operation);archive.mkdir(mode=0o700)
            driver.save(archive/'state.json',dict(identity=identity,stage='execution_intent',maintenance=held,
                command_sha256='b'*64,container='fixed-owned-helper'))
            driver.save(archive/'output.json',dict(returncode=0,stdout=json.dumps(report(sources)),stderr=''))
            original=driver.read(archive/'output.json')
            with patch.object(driver,'ROOT',root),patch.object(driver,'require_idle',return_value=(held,{})),\
                    patch.object(driver,'await_retirement') as retired,\
                    patch.object(driver.subprocess,'run',side_effect=AssertionError('no repeated Docker run')):
                receipt=driver.qualify(namespace,image,operation,observe=True)
                self.assertEqual(driver.qualify(namespace,image,operation,observe=True),receipt)
            retired.assert_called_once_with('fixed-owned-helper')
            self.assertEqual(driver.read(archive/'output.json'),original)
            self.assertEqual(json.loads(driver.read(archive/'state.json'))['stage'],'qualified')


if __name__=='__main__':unittest.main()
