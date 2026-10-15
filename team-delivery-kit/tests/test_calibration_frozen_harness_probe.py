import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import calibration_frozen_harness_probe as diagnostic


class FrozenHarnessDiagnosticTests(unittest.TestCase):
    def fixture(self,source):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup);root=Path(folder.name)
        (root/'test_frozen.py').write_text(source);data=source.encode();sha=hashlib.sha256(data).hexdigest()
        manifest=json.dumps(dict(files={'test_frozen.py':dict(bytes=len(data),sha256=sha)}),sort_keys=True)
        (root/'manifest.json').write_text(manifest)
        return root,hashlib.sha256(manifest.encode()).hexdigest(),{'test_frozen.py':sha}

    def test_actual_frozen_pass_fail_and_error_are_not_delivery_authority(self):
        source='''import unittest
class Frozen(unittest.TestCase):
 def test_pass(self): print('PRIVATE_DIAGNOSTIC_VALUE');self.assertEqual(2,2)
 def test_fail(self): self.assertEqual(2,3)
 def test_error(self): raise RuntimeError('PRIVATE_DIAGNOSTIC_VALUE')
'''
        root,manifest,hashes=self.fixture(source);before={p.name:p.read_bytes() for p in root.iterdir()}
        result=diagnostic.run(root,manifest,hashes,{'test_frozen.py':['test_pass','test_fail','test_error']})
        facts=result['modules']['test_frozen.py'];self.assertEqual((facts['tests'],facts['failures'],facts['errors']),(3,1,1))
        failed=next(v for v in facts['outcomes'] if v['outcome']=='failure')
        self.assertEqual(failed['phase'],'test_body');self.assertEqual(failed['source_frames'][-1]['function'],'test_fail')
        self.assertNotIn('PRIVATE_DIAGNOSTIC_VALUE',json.dumps(result))
        self.assertEqual(before,{p.name:p.read_bytes() for p in root.iterdir()})
        for field in ('calibration_approved','red_approved','product_green','author_retry_authorized','execution_authorized','delivery_approval'):
            self.assertIs(result[field],False)

    def test_selection_or_hash_drift_cannot_masquerade_as_full_candidate_module(self):
        root,manifest,hashes=self.fixture('import unittest\nclass Frozen(unittest.TestCase):\n def test_a(self):pass\n def test_b(self):pass\n')
        with self.assertRaises(ValueError):diagnostic.run(root,manifest,hashes,{'test_frozen.py':['test_a']})
        with self.assertRaises(ValueError):diagnostic.run(root,manifest,{'test_frozen.py':'a'*64},{'test_frozen.py':['test_a','test_b']})

    def test_subtest_failure_is_preserved_under_its_parent_method(self):
        source='''import unittest
class Frozen(unittest.TestCase):
 def test_cases(self):
  for number in (1,2):
   with self.subTest(number=number):self.assertEqual(number,1)
'''
        root,manifest,hashes=self.fixture(source)
        result=diagnostic.run(root,manifest,hashes,{'test_frozen.py':['test_cases']})
        facts=result['modules']['test_frozen.py'];self.assertEqual((facts['tests'],facts['failures'],facts['errors']),(1,1,0))
        self.assertEqual(facts['outcomes'][0]['test'],'Frozen.test_cases');self.assertEqual(facts['outcomes'][0]['outcome'],'failure')

    def test_setup_assertion_is_not_misreported_as_a_functional_test_body_failure(self):
        source='''import unittest
class Frozen(unittest.TestCase):
 def setUp(self):self.fail('private setup condition')
 def test_behavior(self):raise RuntimeError('must not execute')
'''
        root,manifest,hashes=self.fixture(source)
        result=diagnostic.run(root,manifest,hashes,{'test_frozen.py':['test_behavior']})
        item=result['modules']['test_frozen.py']['outcomes'][0]
        self.assertEqual(item['phase'],'set_up');self.assertEqual(item['source_frames'][-1]['function'],'setUp')
        self.assertNotIn('private setup condition',json.dumps(item))
