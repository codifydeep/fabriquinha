"""Real isolated-test execution on synthetic files, not a native delivery."""
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import post_green_sensitivity as runner
from broker import quality_lifecycle_v2 as q
from generic_calibration_bundle_writer import inventory
from generic_harness_calibration import digest as policy_digest


class PostGreenSensitivityTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.candidate=self.root/'candidate';self.controls=self.root/'controls'
        self.candidate.mkdir();self.controls.mkdir()
        files={'app/value.txt':'ready',
            'tests/test_old.py':'import unittest\nfrom pathlib import Path\nVALUE=Path(__file__).parents[1]/"app/value.txt"\nclass Old(unittest.TestCase):\n def test_exists(self):self.assertTrue(VALUE.exists())\n',
            'tests/test_new.py':'import unittest\nfrom pathlib import Path\nVALUE=Path(__file__).parents[1]/"app/value.txt"\nclass New(unittest.TestCase):\n def test_ready(self):self.assertEqual(VALUE.read_text(),"ready")\n'}
        controls={'positive.txt':'ready','negative.txt':'broken'}
        for directory,contents in ((self.candidate,files),(self.controls,controls)):
            for name,text in contents.items():
                path=directory/name;path.parent.mkdir(exist_ok=True,parents=True);path.write_text(text)
            (directory/'manifest.json').write_text(inventory(contents))
        hashes={p:hashlib.sha256(t.encode()).hexdigest() for p,t in files.items() if p.startswith('tests/')}
        self.plan=dict(version=2,policy=q.POLICY,run_id='synthetic',issue_id='fixture',contract_sha256='a'*64,
            base_sha='b'*40,author='author',reviewer='reviewer',criteria=['A01'],
            baseline_tests={'tests/test_old.py':hashes['tests/test_old.py']},new_tests=['tests/test_new.py'],
            protected_files=['tests/test_old.py','tests/test_new.py'],
            product_files=['app/value.txt'],criterion_tests={'A01':[dict(path='tests/test_new.py',method='test_ready')]})
        common=dict(run_id='synthetic',issue_id='fixture',contract_sha256='a'*64,plan_sha256=q.digest(self.plan))
        red=dict(**common,operation='observed_red_v2',task_id='tests-task',manifest_sha256='c'*64,tests=hashes,
            suite_complete=True,tests_run=2,skipped=0,errors=0,exit_code=1,
            failures=[dict(path='tests/test_new.py',method='test_ready',phase='test_body',kind='assertion')])
        review=dict(**common,operation='independent_test_review_v2',task_id='review-task',author='author',reviewer='reviewer',
            manifest_sha256='c'*64,red_sha256=q.digest(red),decision='approve_tests',criteria=['A01'],complete_reads=True,read_only=True)
        green=dict(**common,operation='observed_green_v2',task_id='implementation-task',
            manifest_sha256=hashlib.sha256((self.candidate/'manifest.json').read_bytes()).hexdigest(),commit_sha='d'*40,
            red_sha256=q.digest(red),test_review_sha256=q.digest(review),tests=hashes,
            suite_complete=True,tests_run=2,skipped=0,errors=0,exit_code=0,failures=[])
        self.evidence=dict(red=red,test_review=review,green=green)
        self.policy=dict(version='post_green_sensitivity_policy_v2',engine='unittest_path_fixtures_v2',
            source_task='00000000-0000-4000-8000-000000000001',execution_sha256='e'*64,plan_sha256=q.digest(self.plan),
            candidate_manifest_sha256=green['manifest_sha256'],
            controls_manifest_sha256=hashlib.sha256((self.controls/'manifest.json').read_bytes()).hexdigest(),criteria=['A01'],
            test_sha256=hashes,
            modules=[dict(path=p,classes={cls:[method]},fixtures=[dict(attribute='VALUE',product_path='app/value.txt',positive_fixture='positive.txt')])
                for p,cls,method in (('tests/test_old.py','Old','test_exists'),('tests/test_new.py','New','test_ready'))],
            negatives=[dict(id='broken',module='tests/test_new.py',class_name='New',method='test_ready',
                replacements=[dict(attribute='VALUE',fixture='negative.txt')],criteria=['A01'])])

    def call(self):return runner.run(self.candidate,self.controls,self.plan,self.evidence,self.policy,policy_digest(self.policy))

    def test_positive_is_exact_green_bytes_and_each_negative_runs_full_inventory(self):
        before={p:p.read_bytes() for p in self.candidate.rglob('*') if p.is_file()}
        value=self.call();facts=value['sensitivity']
        self.assertEqual(facts['controls'][0]['tests_run'],2)
        self.assertEqual(value['positive']['tests_run'],2)
        self.assertEqual(facts['controls'][0]['failures'][0]['path'],'tests/test_new.py')
        proof=q.qualify_sensitivity(self.plan,{**self.evidence,'sensitivity':facts})
        self.assertFalse(proof['merge_authorized']);self.assertFalse(value['delivery_approval'])
        self.assertEqual(before,{p:p.read_bytes() for p in self.candidate.rglob('*') if p.is_file()})

    def test_reference_implementation_different_from_green_is_forbidden(self):
        (self.controls/'positive.txt').write_text('independent implementation')
        with self.assertRaises(ValueError):self.call()

    def test_green_with_partial_inventory_or_wrong_test_hash_cannot_start(self):
        self.policy['modules']=self.policy['modules'][1:]
        self.policy['test_sha256'].pop('tests/test_old.py')
        with self.assertRaises(ValueError):self.call()

    def test_legacy_policy_cannot_be_upgraded_to_post_green_evidence(self):
        self.policy['version']='generic_harness_calibration_v2'
        with self.assertRaises(ValueError):self.call()

    def test_surviving_negative_does_not_qualify(self):
        self.policy['negatives'][0]['replacements'][0]['fixture']='surviving.txt'
        (self.controls/'surviving.txt').write_text('ready')
        values={'positive.txt':'ready','surviving.txt':'ready'}
        (self.controls/'negative.txt').unlink();(self.controls/'manifest.json').write_text(inventory(values))
        self.policy['controls_manifest_sha256']=hashlib.sha256((self.controls/'manifest.json').read_bytes()).hexdigest()
        with self.assertRaises(ValueError):self.call()

    def test_actual_setup_assertion_is_not_a_killed_behavioral_mutation(self):
        path=self.candidate/'tests/test_new.py'
        text=path.read_text().replace(' def test_ready',
            ' def setUp(self):\n  if VALUE.read_text()=="broken":self.fail("setup failure")\n def test_ready')
        path.write_text(text)
        files={p.relative_to(self.candidate).as_posix():p.read_text() for p in self.candidate.rglob('*')
            if p.is_file() and p.name!='manifest.json'}
        (self.candidate/'manifest.json').write_text(inventory(files))
        tests={**self.evidence['red']['tests'],'tests/test_new.py':hashlib.sha256(text.encode()).hexdigest()}
        self.evidence['red']['tests']=tests
        self.evidence['test_review']['red_sha256']=q.digest(self.evidence['red'])
        self.evidence['green'].update(tests=tests,red_sha256=q.digest(self.evidence['red']),
            test_review_sha256=q.digest(self.evidence['test_review']),
            manifest_sha256=hashlib.sha256((self.candidate/'manifest.json').read_bytes()).hexdigest())
        self.policy.update(test_sha256=tests,candidate_manifest_sha256=self.evidence['green']['manifest_sha256'])
        with self.assertRaises(ValueError):self.call()


if __name__=='__main__':unittest.main()
