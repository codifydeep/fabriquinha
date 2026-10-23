"""Qualification receipt validation, never real-agent approval."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import qualify_quality_review_stop as driver
import recover_quality_review_completion as reader
from qualify_quality_review_stop import validate_report
from test_review_execution_evidence import evidence,scale_evidence


class QualityReviewStopQualificationTests(unittest.TestCase):
    def report(self):
        return dict(operation='real_hermes_review_stop_loop_canary_v1',status='passed',provider='fixed_loopback_not_model',
            model_calls=0,fixed_provider_calls=3,total_fixed_provider_calls=31,execution_controls=evidence(),
            scale_controls=scale_evidence(),fixture_source_sha256=driver.sha((driver.ROOT/'review_execution_evidence.py').read_bytes()),
            feedback_rounds=1,same_agent=True,max_iterations=40,
            acp=True,protected_files_unchanged=True,tests_approved=False,delivery_approval=False,
            guard_sources=dict(feedback='a'*64,phase='b'*64,verdict='c'*64,installer='d'*64))

    def test_only_actual_bounded_acp_loop_facts_with_exact_guards_qualify(self):
        report=self.report();guards=report['guard_sources']
        self.assertEqual(validate_report(report,guards),report)
        for change in (dict(acp=False),dict(provider='openrouter'),dict(model_calls=1),dict(model_calls=False),
                dict(max_iterations=999),dict(same_agent=False),dict(fixed_provider_calls=2),
                dict(tests_approved=True),dict(guard_sources={**guards,'feedback':'0'*64})):
            value={**report,**change}
            with self.subTest(change=change),self.assertRaises(ValueError):validate_report(value,guards)

    def test_lost_final_receipt_resumes_preserved_success_output_without_reexecuting(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();(root/'tests').mkdir();script=b'FILES={"app.py":b"x","tests/test_new.py":b"y"}\n'
            fixture=(driver.ROOT/'review_execution_evidence.py').read_bytes()
            (root/'review_execution_evidence.py').write_bytes(fixture)
            (root/'tests/quality_review_stop_canary.py').write_bytes(script)
            guards={}
            for key,name in driver.GUARDS.items():
                (root/name).parent.mkdir(parents=True,exist_ok=True)
                (root/name).write_bytes(key.encode());guards[key]=driver.sha(key.encode())
            report={**self.report(),'guard_sources':guards}
            identity=dict(namespace='delivery-kit-test',image='sha256:'+'e'*64,operation='a0000000-0000-4000-8000-000000000001',
                script_sha256=driver.sha(script),guards=guards,fixture_sha256=driver.sha(fixture))
            maintenance=dict(stage='sealed',operation_id='held')
            state=dict(identity=identity,stage='execution_intent',maintenance=maintenance,command_sha256='command',container_name='fixed-name')
            driver.save(root/'state.json',state)
            driver.save(root/'output.json',dict(returncode=0,stdout=json.dumps(report),stderr=''))
            original=(root/'output.json').read_bytes()
            with patch.object(driver,'ROOT',root),patch.object(driver,'require_idle',return_value=(maintenance,{})),\
                    patch.object(driver,'await_retirement') as retire,\
                    patch.object(driver.subprocess,'run',side_effect=AssertionError('must not execute again')):
                receipt=driver.observe(root,identity)
                self.assertTrue(receipt['container_retired']);retire.assert_called_once_with('fixed-name')
                self.assertEqual(driver.observe(root,identity),receipt)
            self.assertEqual((root/'output.json').read_bytes(),original)
            self.assertEqual(json.loads((root/'state.json').read_bytes())['stage'],'qualified')

    def test_recovery_reader_requires_fixture_identity_as_well_as_report_hash(self):
        namespace='delivery-kit-test';identity='a0000000-0000-4000-8000-000000000001'
        maintenance='a0000000-0000-4000-8000-000000000002'
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve()
            for path in list(driver.GUARDS.values())+['tests/quality_review_stop_canary.py','review_execution_evidence.py']:
                target=root/path;target.parent.mkdir(parents=True,exist_ok=True)
                target.write_bytes((driver.ROOT/path).read_bytes())
            guards={k:driver.sha((root/p).read_bytes()) for k,p in driver.GUARDS.items()}
            report={**self.report(),'guard_sources':guards}
            stdout=json.dumps(report);fixture=report['fixture_source_sha256']
            receipt=dict(operation='qualified_review_stop_worker_v1',namespace=namespace,
                qualification_id=identity,maintenance_operation=maintenance,worker_image='sha256:'+'e'*64,
                guards=guards,container_retired=True,model_calls=0,tests_approved=False,delivery_approval=False,
                output_sha256=driver.sha(stdout.encode()),command_sha256='a'*64,
                script_sha256=driver.sha((root/'tests/quality_review_stop_canary.py').read_bytes()),
                fixture_sha256=fixture,report=report)
            state=dict(stage='qualified',receipt=receipt,command_sha256='a'*64,
                identity=dict(image=receipt['worker_image'],fixture_sha256=fixture))
            archive=root/'.local-test/backups'/('quality-review-stop-'+identity)
            archive.mkdir(parents=True)
            driver.save(archive/'state.json',state)
            driver.save(archive/'output.json',dict(returncode=0,stdout=stdout,stderr=''))
            with patch.object(reader,'ROOT',root),patch.object(driver,'ROOT',root):
                self.assertEqual(reader.qualification(namespace,identity,maintenance),receipt)
                state['receipt']['fixture_sha256']='0'*64
                driver.save_state(archive/'state.json',state)
                with self.assertRaises(ValueError):reader.qualification(namespace,identity,maintenance)


if __name__=='__main__':unittest.main()
