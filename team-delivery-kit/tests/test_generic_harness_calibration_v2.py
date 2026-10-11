import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from generic_harness_calibration import digest
from generic_harness_calibration_v2 import run,validate_policy,validate_receipt


class MultiPathCalibrationTests(unittest.TestCase):
    def snapshot(self,root,files):
        for name,text in files.items():
            p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text)
        inventory={name:{'bytes':(root/name).stat().st_size,
            'sha256':hashlib.sha256((root/name).read_bytes()).hexdigest()} for name in files}
        raw=json.dumps({'files':inventory},sort_keys=True).encode()
        (root/'manifest.json').write_bytes(raw)
        return hashlib.sha256(raw).hexdigest(),inventory

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.candidate=Path(self.temp.name)/'candidate';self.controls=Path(self.temp.name)/'controls'
        self.candidate.mkdir();self.controls.mkdir()
        test=('import unittest\nfrom pathlib import Path\n'
            'APP_JS=Path(__file__).parents[1]/"app/app.js"\n'
            'INDEX_HTML=Path(__file__).parents[1]/"app/index.html"\n'
            'class ContractTests(unittest.TestCase):\n'
            ' def test_script(self):\n'
            '  value=APP_JS.read_text()\n'
            '  if value=="error": raise RuntimeError("not an assertion")\n'
            '  if value=="skip": self.skipTest("not a regression")\n'
            '  self.assertEqual(value,"script-good")\n'
            '  self.assertEqual(INDEX_HTML.read_text(),"markup-good")\n'
            ' def test_markup(self):\n'
            '  self.assertEqual(INDEX_HTML.read_text(),"markup-good")\n'
            '  self.assertEqual(APP_JS.read_text(),"script-good")\n')
        manifest,files=self.snapshot(self.candidate,{'tests/test_ui.py':test,
            'app/app.js':'script-broken','app/index.html':'markup-broken'})
        self.control_files={'js-positive.js':'script-good','html-positive.html':'markup-good',
            'js-negative.js':'script-broken','html-negative.html':'markup-broken'}
        controls,_=self.snapshot(self.controls,self.control_files)
        self.policy=dict(version='generic_harness_calibration_v2',engine='unittest_path_fixtures_v2',
            source_task='01a12370-34e8-7a3a-93f8-e8baec192a8e',execution_sha256='a'*64,plan_sha256='b'*64,
            candidate_manifest_sha256=manifest,controls_manifest_sha256=controls,criteria=['A01','A02'],
            test_sha256={'tests/test_ui.py':files['tests/test_ui.py']['sha256']},
            previous_methods={'tests/test_ui.py':{'ContractTests':['test_script','test_markup']}},
            modules=[dict(path='tests/test_ui.py',classes={'ContractTests':['test_script','test_markup']},
                fixtures=[dict(attribute='APP_JS',product_path='app/app.js',positive_fixture='js-positive.js'),
                    dict(attribute='INDEX_HTML',product_path='app/index.html',positive_fixture='html-positive.html')])],
            negatives=[dict(id='script',module='tests/test_ui.py',class_name='ContractTests',method='test_script',
                    replacements=[dict(attribute='APP_JS',fixture='js-negative.js')],criteria=['A01']),
                dict(id='markup',module='tests/test_ui.py',class_name='ContractTests',method='test_markup',
                    replacements=[dict(attribute='INDEX_HTML',fixture='html-negative.html')],criteria=['A02'])])

    def test_both_positive_paths_and_independent_negatives_preserve_delivery(self):
        before={p:p.read_bytes() for p in self.candidate.rglob('*') if p.is_file()}
        r=run(self.candidate,self.controls,self.policy,digest(self.policy))
        self.assertEqual(r['positive']['tests'],2)
        self.assertEqual({k:v['failures'] for k,v in r['negative_controls'].items()},{'script':1,'markup':1})
        for key in ('product_green','red_approved','delivery_approval'):self.assertIs(r[key],False)
        self.assertEqual(before,{p:p.read_bytes() for p in self.candidate.rglob('*') if p.is_file()})

    def test_v1_engine_or_receipt_is_not_converted(self):
        p=copy.deepcopy(self.policy);p['engine']='unittest_path_fixture_v1'
        with self.assertRaises(ValueError):validate_policy(p,digest(p))
        r=run(self.candidate,self.controls,self.policy,digest(self.policy));r['operation']='generic_harness_calibration_v1'
        with self.assertRaises(ValueError):validate_receipt(r,self.policy,digest(self.policy))

    def test_duplicate_foreign_or_unbound_fixture_is_rejected(self):
        for mutate in (lambda p:p['modules'][0]['fixtures'].append(p['modules'][0]['fixtures'][0]),
                lambda p:p['modules'][0]['fixtures'][0].update(product_path='tests/test_ui.py'),
                lambda p:p['modules'][0]['fixtures'][0].update(attribute='UNKNOWN_PATH'),
                lambda p:p['negatives'][0]['replacements'][0].update(attribute='FOREIGN'),
                lambda p:p['negatives'][0]['replacements'][0].update(fixture='../escape')):
            p=copy.deepcopy(self.policy);mutate(p)
            with self.assertRaises(ValueError):run(self.candidate,self.controls,p,digest(p))

    def test_discovery_criteria_and_previous_methods_are_not_weakened(self):
        for mutate in (lambda p:p['modules'][0].update(classes={'ContractTests':['test_script']}),
                lambda p:p['negatives'][0].update(criteria=[]),
                lambda p:p['modules'][0]['fixtures'][0].update(product_path='app/index.html')):
            p=copy.deepcopy(self.policy);mutate(p)
            with self.assertRaises(ValueError):run(self.candidate,self.controls,p,digest(p))

    def test_errors_skips_or_no_assertion_failure_are_rejected(self):
        for value in ('error','skip','script-good'):
            files={**self.control_files,'js-negative.js':value};controls,_=self.snapshot(self.controls,files)
            p=copy.deepcopy(self.policy);p['controls_manifest_sha256']=controls
            with self.assertRaises(ValueError):run(self.candidate,self.controls,p,digest(p))

    def test_receipt_authority_partial_results_and_stale_hash_are_rejected(self):
        r=run(self.candidate,self.controls,self.policy,digest(self.policy))
        for mutate in (lambda x:x.update(delivery_approval=True),lambda x:x.update(negative_controls={}),
                lambda x:x['positive'].update(tests=True),lambda x:x.update(policy_sha256='c'*64)):
            bad=copy.deepcopy(r);mutate(bad)
            with self.assertRaises(ValueError):validate_receipt(bad,self.policy,digest(self.policy))
