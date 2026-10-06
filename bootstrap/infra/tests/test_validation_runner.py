import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from validation_runner import run,digest,record_failure

class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        (self.root/'score.py').write_text('def winner(a,b):\n    return None\n')
        (self.root/'test_score.py').write_text('import unittest\nfrom score import winner\nclass Old(unittest.TestCase):\n    def test_old(self): self.assertIsNone(winner(0,0))\n')
        tests='import unittest\nfrom score import winner\nclass New(unittest.TestCase):\n'
        for i,(a,b,value) in enumerate([(13,0,'A'),(0,13,'B'),(0,0,None),(12,12,'A'),(12,11,'A')]):
            tests+=f'    def test_{i}(self): self.assertEqual(winner({a},{b}),{value!r})\n'
        (self.root/'test_new_score.py').write_text(tests)
        self.contract=dict(regression_sha256=digest(self.root/'test_score.py'),fixture_sha256=digest(self.root/'score.py'))

    def test_real_red_green_capture_stderr(self):
        red=run(self.root,'red',self.contract)
        self.assertEqual(red['red_failures'],4)
        (self.root/'score.py').write_text('def winner(a,b):\n    return "A" if a>=12 else "B" if b>=12 else None\n')
        green=run(self.root,'green',self.contract)
        self.assertTrue(green['accepted'])
        report=json.loads((self.root/'validation-result.json').read_text())
        self.assertEqual(report['tests_run'],6)
        self.assertIn('OK',(self.root/'green.log').read_text())

    def test_fake_function_rejected_before_execution(self):
        with (self.root/'test_new_score.py').open('a') as f: f.write('\ndef winner(a,b): raise NotImplementedError\n')
        with self.assertRaisesRegex(ValueError,'fake winner'): run(self.root,'red',self.contract)

    def test_green_without_red_rejected(self):
        with self.assertRaises(FileNotFoundError): run(self.root,'green',self.contract)

    def test_implementation_before_red_rejected(self):
        (self.root/'score.py').write_text('def winner(a,b): return "A"\n')
        with self.assertRaisesRegex(ValueError,'precede'): run(self.root,'red',self.contract)

    def test_changed_tests_between_stages_rejected(self):
        run(self.root,'red',self.contract)
        with (self.root/'test_new_score.py').open('a') as f: f.write('\n# changed\n')
        with self.assertRaisesRegex(ValueError,'identical'): run(self.root,'green',self.contract)

    def test_duplicate_failure_detection_resets_on_new_code(self):
        self.assertEqual(record_failure(self.root,'same'),1)
        self.assertEqual(record_failure(self.root,'same'),2)
        (self.root/'score.py').write_text('changed')
        self.assertEqual(record_failure(self.root,'same'),1)
