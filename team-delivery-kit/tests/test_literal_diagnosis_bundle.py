import json
from pathlib import Path
import tempfile
import unittest
import literal_diagnosis_bundle as bundle
import test_literal_test_maintenance as fixture


class DiagnosisBundleTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name)
        self.manifests={};self.raw={};self.target=self.root/'bundle';self.target.mkdir()
        for name,n in (('original',1),('seed',2),('candidate',3)):
            root=self.root/name;root.mkdir();(root/'tests').mkdir()
            raw=fixture.LiteralMaintenanceTests.SOURCE.replace(b'const value = 1;',('const value = %s;\n'%n).encode())
            (root/'tests/test.py').write_bytes(raw);self.raw[name]=raw
            manifest=bundle.encoded(dict(files={'tests/test.py':dict(bytes=len(raw),sha256=bundle.sha(raw))}))
            (root/'manifest.json').write_bytes(manifest);self.manifests[name]=bundle.sha(manifest)

    def run_bundle(self,mode='create'):
        return bundle.build(*(self.root/n for n in ('original','seed','candidate')),self.target,self.manifests,'tests/test.py',mode)

    def test_only_supported_previous_subpaths_contain_exact_original_and_seed_bytes(self):
        result=self.run_bundle()
        for name in ('original','seed'):
            self.assertEqual((self.target/name/'tests/test.py').read_bytes(),self.raw[name])
        self.assertEqual(set(json.loads((self.target/'manifest.json').read_text())['files']),
            {'original/tests/test.py','seed/tests/test.py','report.json'})
        self.assertEqual(result,self.run_bundle('verify'));self.assertEqual(result,self.run_bundle())
        self.assertFalse(result['delivery_approval']);self.assertFalse(result['source_reset'])
        self.assertEqual(result['model_calls'],0)

    def test_report_distinguishes_literal_ranges_and_inherited_from_current_delta(self):
        report=self.run_bundle()['report']
        for name in self.raw:
            self.assertEqual(report['literal_ranges'][name]['test_sha256'],bundle.sha(self.raw[name]))
            self.assertLessEqual(report['literal_ranges'][name]['start_line'],4)
            self.assertGreaterEqual(report['literal_ranges'][name]['end_line'],5)
        self.assertTrue(report['current_delta']['outside_literal_bytes_preserved'])

    def test_missing_or_changed_source_and_outside_literal_edits_are_refused(self):
        self.manifests['seed']='a'*64
        with self.assertRaises(ValueError):self.run_bundle()
        self.assertFalse(list(self.target.iterdir()))

    def test_partial_matching_projection_resumes_but_unknown_or_different_bytes_do_not(self):
        dest=self.target/'original/tests/test.py';dest.parent.mkdir(parents=True);dest.write_bytes(self.raw['original'])
        self.run_bundle();dest.write_bytes(b'altered')
        with self.assertRaises(ValueError):self.run_bundle()
        dest.write_bytes(self.raw['original']);(self.target/'unexpected').write_text('unowned')
        with self.assertRaises(ValueError):self.run_bundle()

    def test_symlinks_and_verify_of_unmaterialized_projection_are_rejected(self):
        with self.assertRaises(ValueError):self.run_bundle('verify')
        (self.target/'original').symlink_to(self.root/'original',target_is_directory=True)
        with self.assertRaises(ValueError):self.run_bundle()
