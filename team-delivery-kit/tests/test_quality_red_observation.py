"""Real unittest execution on frozen synthetic inputs; not native qualification."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import quality_red_observation as runner
from broker import quality_lifecycle_v2 as quality
from broker.test_first_protocol import prepare_red
from test_portable_contract import contract


class QualityRedObservationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve()
        self.base,self.work,self.snapshot=(self.root/p for p in ('base','work','snapshot'))
        for p in (self.base,self.work,self.snapshot):p.mkdir()
        self.spec=contract()
        self.old={'AGENTS.md':b'Preserve tests\n','app.py':b'VALUE=0\n',
            'tests/test_old.py':b'import unittest\nimport app\nclass Old(unittest.TestCase):\n def test_old(self):self.assertGreaterEqual(app.VALUE,0)\n'}
        self.new=b'import unittest\nimport app\nclass New(unittest.TestCase):\n def test_new(self):self.assertEqual(app.VALUE,1,"PRIVATE_TEST_DETAIL")\n'
        self.task='30000000-0000-4000-8000-000000000001'

    def prepare(self,new=None,old=None):
        files=self.old if old is None else old
        for name,data in files.items():
            for root in (self.base,self.work):
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
        (self.work/'tests/test_new.py').write_bytes(self.new if new is None else new)
        (self.base/'contract.json').write_text(json.dumps(self.spec))
        hashes={name:hashlib.sha256(data).hexdigest() for name,data in files.items()}
        hashes['contract.json']=hashlib.sha256((self.base/'contract.json').read_bytes()).hexdigest()
        (self.base/'manifest.json').write_text(json.dumps(dict(base_sha='b'*40,files=hashes)))
        self.prepared=prepare_red(self.base,self.work,self.snapshot,self.spec)
        self.plan=dict(version=2,policy=quality.POLICY,run_id='run',issue_id='issue',
            contract_sha256=quality.digest(self.spec),base_sha='b'*40,author='author',reviewer='reviewer',
            criteria=['A01'],baseline_tests={'tests/test_old.py':hashes['tests/test_old.py']},
            new_tests=['tests/test_new.py'],product_files=['app.py'],
            protected_files=['AGENTS.md','tests/test_old.py','tests/test_new.py'],
            criterion_tests={'A01':[dict(path='tests/test_new.py',method='test_new')]})

    def call(self):
        return runner.run(self.base,self.snapshot,self.plan,self.task,
            self.prepared['base_manifest_sha256'],self.prepared['manifest_sha256'])

    def test_actual_red_executes_all_tests_preserves_bytes_and_grants_nothing(self):
        self.prepare();before={p:p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        report=self.call()
        self.assertEqual(report['operation'],'full_suite_red_observation_v2')
        self.assertEqual(report['red']['tests_run'],2)
        self.assertEqual(report['red']['failures'],[dict(path='tests/test_new.py',method='test_new',phase='test_body',kind='assertion')])
        quality.red(self.plan,report['red'])
        self.assertFalse(report['execution_authorized']);self.assertFalse(report['delivery_approval'])
        self.assertNotIn('PRIVATE_TEST_DETAIL',json.dumps(report))
        self.assertEqual(before,{p:p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
        self.assertEqual(self.call(),report)

    def test_all_green_cannot_be_red(self):
        self.prepare(new=self.new.replace(b'app.VALUE,1',b'app.VALUE,0'))
        with self.assertRaises(runner.Rejected) as caught:self.call()
        self.assertEqual(caught.exception.category,'suite_not_behavioral_red')

    def test_baseline_failure_cannot_be_new_behavior_red(self):
        old={**self.old,'tests/test_old.py':self.old['tests/test_old.py'].replace(b'app.VALUE,0',b'app.VALUE,10')}
        self.prepare(old=old)
        with self.assertRaises(runner.Rejected) as caught:self.call()
        self.assertEqual(caught.exception.category,'baseline_regression')

    def test_setup_teardown_and_class_setup_assertions_are_not_red(self):
        templates=[
            'class New(unittest.TestCase):\n def setUp(self):self.fail("private")\n def test_new(self):pass\n',
            'class New(unittest.TestCase):\n def tearDown(self):self.fail("private")\n def test_new(self):pass\n',
            'class New(unittest.TestCase):\n @classmethod\n def setUpClass(cls):raise AssertionError("private")\n def test_new(self):pass\n',
            'class New(unittest.TestCase):\n def setUp(self):self.addCleanup(lambda:self.fail("private"))\n def test_new(self):pass\n',
        ]
        for body in templates:
            with self.subTest(body=body),tempfile.TemporaryDirectory() as d:
                # Each attempt has separate immutable artifacts and module state.
                previous=(self.base,self.work,self.snapshot)
                self.base,self.work,self.snapshot=(Path(d).resolve()/p for p in ('base','work','snapshot'))
                for p in (self.base,self.work,self.snapshot):p.mkdir()
                try:
                    self.prepare(new=('import unittest\n'+body).encode())
                    with self.assertRaises(runner.Rejected):self.call()
                finally:self.base,self.work,self.snapshot=previous

    def test_import_error_skip_and_expected_failure_are_not_red(self):
        for prefix in ('import unavailable_quality_dependency\n',
                '@unittest.skip("do not execute")\n','@unittest.expectedFailure\n'):
            text=self.new.decode()
            if prefix.startswith('@'):text=text.replace(' def test_new', ' '+prefix+' def test_new')
            else:text=prefix+text
            with self.subTest(prefix=prefix),tempfile.TemporaryDirectory() as d:
                previous=(self.base,self.work,self.snapshot)
                self.base,self.work,self.snapshot=(Path(d).resolve()/p for p in ('base','work','snapshot'))
                for p in (self.base,self.work,self.snapshot):p.mkdir()
                try:
                    self.prepare(new=text.encode())
                    with self.assertRaises(runner.Rejected):self.call()
                finally:self.base,self.work,self.snapshot=previous

    def test_load_tests_cannot_select_only_the_new_test(self):
        self.prepare(new=self.new+b'\ndef load_tests(loader,tests,pattern):return unittest.TestSuite()\n')
        with self.assertRaises(runner.Rejected) as caught:self.call()
        self.assertEqual(caught.exception.category,'test_selection_hook_forbidden')

    def test_hash_or_product_edit_cannot_be_reinterpreted_as_red(self):
        self.prepare();(self.snapshot/'app.py').chmod(0o600);(self.snapshot/'app.py').write_text('VALUE=1\n')
        with self.assertRaises(ValueError):self.call()

    def test_manifest_recomputed_after_product_edit_still_rejects_base_divergence(self):
        self.prepare();p=self.snapshot/'app.py';p.chmod(0o600);p.write_text('VALUE=1\n')
        m=self.snapshot/'manifest.json';m.chmod(0o600);value=json.loads(m.read_text())
        value['files']['app.py']={'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
        m.write_text(json.dumps(value));self.prepared['manifest_sha256']=hashlib.sha256(m.read_bytes()).hexdigest()
        with self.assertRaises(runner.Rejected) as caught:self.call()
        self.assertEqual(caught.exception.category,'base_bytes_changed_before_red')

    def test_witness_method_must_exist_in_complete_inventory(self):
        self.prepare();self.plan['criterion_tests']['A01'][0]['method']='test_nonexistent'
        with self.assertRaises(runner.Rejected):self.call()

    def test_snapshot_or_plan_cannot_omit_baseline_tests(self):
        self.prepare();self.plan['baseline_tests']={'tests/other.py':'e'*64}
        self.plan['protected_files'].append('tests/other.py')
        with self.assertRaises(runner.Rejected):self.call()

    def test_body_assertion_cannot_hide_an_additional_teardown_failure(self):
        self.prepare(new=self.new.replace(b' def test_new',b' def tearDown(self):self.fail("private teardown")\n def test_new'))
        with self.assertRaises(runner.Rejected):self.call()

    def test_real_subtest_assertion_is_recorded_under_parent_method(self):
        self.prepare(new=b'import unittest\nimport app\nclass New(unittest.TestCase):\n def test_new(self):\n  for v in (0,1):\n   with self.subTest(v=v):self.assertEqual(app.VALUE,v)\n')
        self.assertEqual(self.call()['red']['tests_run'],2)


if __name__=='__main__':unittest.main()
