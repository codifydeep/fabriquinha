"""Capacity proof validation and observation-only recovery, not a delivery."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import qualify_model_proxy_capacity as driver


class ModelProxyCapacityQualificationTests(unittest.TestCase):
    def report(self):
        return dict(operation='real_http_proxy_capacity_canary_v1',status='passed',source_sha256='a'*64,
            max_request_bytes=2097152,accepted_request_bytes=[600100,2096800],fixed_forwards=2,
            oversized_rejected=True,call_ceiling_preserved=True,counter_preserved=True,
            fixture_max_calls=2,fixture_calls=2,model_calls=0,credentials_mounted=False,
            docker_socket=False,network='none',data_tmpfs=True,tests_approved=False,delivery_approval=False)

    def test_only_actual_bounded_credential_free_http_facts_qualify(self):
        report=self.report();self.assertEqual(driver.validate_report(report,'a'*64),report)
        for change in (dict(source_sha256='b'*64),dict(max_request_bytes=4194304),dict(accepted_request_bytes=[1,2]),
                dict(accepted_request_bytes=[600100,2097153]),dict(model_calls=1),dict(model_calls=False),
                dict(credentials_mounted=True),dict(docker_socket=True),dict(network='host'),
                dict(data_tmpfs=False),
                dict(call_ceiling_preserved=False),dict(counter_preserved=False),dict(oversized_rejected=False),
                dict(fixed_forwards=3),dict(delivery_approval=True),dict(tests_approved=True)):
            with self.subTest(change=change),self.assertRaises(ValueError):
                driver.validate_report({**report,**change},'a'*64)

    def test_lost_receipt_resumes_successful_output_without_repeating_docker(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();(root/'tests').mkdir()
            (root/'model_proxy.py').write_text('fixture-source');(root/'tests/model_proxy_capacity_canary.py').write_text('fixture-script')
            source=driver.sha((root/'model_proxy.py').read_bytes());script=driver.sha((root/'tests/model_proxy_capacity_canary.py').read_bytes())
            identity=dict(namespace='delivery-kit-test',image='sha256:'+'b'*64,
                operation='a0000000-0000-4000-8000-000000000001',source_sha256=source,script_sha256=script)
            state=dict(identity=identity,stage='execution_intent',container_name='fixed-name',
                maintenance=dict(operation_id='held',stage='sealed'),command_sha256='c'*64,volumes_before=[])
            report={**self.report(),'source_sha256':source}
            driver.save(root/'state.json',state);driver.save(root/'output.json',dict(returncode=0,stdout=json.dumps(report),stderr=''))
            original=(root/'output.json').read_bytes()
            with patch.object(driver,'ROOT',root),patch.object(driver,'require_idle',return_value=(state['maintenance'],{})), \
                    patch.object(driver,'volumes',return_value=[]), \
                    patch.object(driver,'await_retirement') as retire, \
                    patch.object(driver.subprocess,'run',side_effect=AssertionError('must not rerun Docker')):
                receipt=driver.observe(root,identity);self.assertEqual(driver.observe(root,identity),receipt)
            retire.assert_called_once_with('fixed-name');self.assertEqual((root/'output.json').read_bytes(),original)
            self.assertEqual(json.loads((root/'state.json').read_bytes())['stage'],'qualified')

    def test_unknown_execution_is_only_observed_not_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();identity=dict(operation='same')
            driver.save(root/'state.json',dict(identity=identity,stage='outcome_unknown'))
            with patch.object(driver.subprocess,'run',side_effect=AssertionError('must not replace pending effect')):
                result=driver.observe(root,identity)
            self.assertEqual(result['stage'],'outcome_unknown');self.assertFalse(result['qualified'])


if __name__=='__main__':unittest.main()
