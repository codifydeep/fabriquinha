import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from broker.assertion_witness import extract, extract_trace


class AssertionWitnessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'tests').mkdir()
        raw = "TITLE = 'prefix-middle-suffix'\nGREEK = 'Σίσυφος task'\n".encode()
        self.path = self.root / 'tests/test_new.py'
        self.path.write_bytes(raw)
        self.hashes = {'tests/test_new.py': hashlib.sha256(raw).hexdigest()}
        (self.root / 'manifest.json').write_text(json.dumps({'files': {
            name: {'sha256': digest} for name, digest in self.hashes.items()}}))

    def test_exact_observed_expected_from_verified_new_fixture(self):
        output = ('FAIL: test_substring (tests.test_new.Case.test_substring)\n'
                  "AssertionError: Lists differ: ['prefix-middle-suffix'] != []\n"
                  'FAIL: test_unicode (tests.test_new.Case.test_unicode)\n'
                  "AssertionError: Lists differ: [] != ['Σίσυφος task']\n")
        result = extract(self.root, self.hashes, output)
        self.assertEqual(result['witnesses'][0]['observed'], ['prefix-middle-suffix'])
        self.assertEqual(result['witnesses'][1]['expected'], ['Σίσυφος task'])
        self.assertEqual(result['output_sha256'], hashlib.sha256(output.encode()).hexdigest())

    def test_arbitrary_log_values_and_other_modules_are_not_published(self):
        for output in (
            'FAIL: test_new (tests.test_new.Case.test_new)\n'
            "AssertionError: Lists differ: ['private-user-data'] != []\n",
            'FAIL: test_new (tests.test_old.Case.test_new)\n'
            "AssertionError: Lists differ: ['prefix-middle-suffix'] != []\n"):
            self.assertEqual(extract(self.root, self.hashes, output)['witnesses'], [])

    def test_hash_mismatch_cannot_publish_witness(self):
        self.path.write_text('changed')
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            extract(self.root, self.hashes, '')

    def test_no_python_expression_evaluation(self):
        output = ('FAIL: test_new (tests.test_new.Case.test_new)\n'
                  "AssertionError: Lists differ: __import__('os').system('false') != []\n")
        self.assertEqual(extract(self.root, self.hashes, output)['witnesses'], [])

    def test_bounded_paths_and_output(self):
        with self.assertRaisesRegex(ValueError, 'bounded'):
            extract(self.root, self.hashes, 'a' * 65537)
        with self.assertRaisesRegex(ValueError, 'path'):
            extract(self.root, {'../secret.py': 'a' * 64}, '')

    def test_trace_anchors_are_hash_bound_without_log_messages(self):
        raw=b'import unittest\nclass Case(unittest.TestCase):\n def test_x(self):\n  self.assertTrue(report["stale_discarded"], "private message")\n'
        self.path.write_bytes(raw);self.hashes={'tests/test_new.py':hashlib.sha256(raw).hexdigest()}
        (self.root/'manifest.json').write_text(json.dumps({'files':{p:{'sha256':h} for p,h in self.hashes.items()}}))
        output='FAIL: test_x (tests.test_new.Case.test_x)\nTraceback (most recent call last):\n  File "/delivery/tests/test_new.py", line 4, in test_x\nAssertionError: False is not true : private message\n'
        r=extract_trace(self.root,self.hashes,output)
        self.assertEqual(r['anchors'][0]['line'],4)
        self.assertEqual(r['anchors'][0]['assertion'],'assertTrue')
        self.assertEqual(r['anchors'][0]['fields'],['stale_discarded'])
        self.assertEqual(r['anchors'][0]['observed_boolean'],False)
        self.assertNotIn('private message',json.dumps(r))
        self.assertEqual(extract_trace(self.root,self.hashes,output.replace('line 4','line 3'))['anchors'],[])

    def test_membership_operands_only_publish_literals_from_same_assertion(self):
        raw=b'import unittest\nOTHER="other-fixture"\nclass Case(unittest.TestCase):\n def test_x(self):\n  self.assertIn("fixture-item", report["rendered"])\n'
        self.path.write_bytes(raw);self.hashes={'tests/test_new.py':hashlib.sha256(raw).hexdigest()}
        (self.root/'manifest.json').write_text(json.dumps({'files':{p:{'sha256':h} for p,h in self.hashes.items()}}))
        prefix='FAIL: test_x (tests.test_new.Case.test_x)\n  File "/delivery/tests/test_new.py", line 5, in test_x\nAssertionError: '
        r=extract_trace(self.root,self.hashes,prefix+"'fixture-item' not found in []\n")
        self.assertEqual(r['anchors'][0]['membership'],dict(expected_member='fixture-item',observed_container=[]))
        r=extract_trace(self.root,self.hashes,prefix+"'fixture-item' not found in ['other-fixture']\n")
        self.assertEqual(r['anchors'][0]['membership']['observed_container'],['other-fixture'])
        for suffix in ("'private' not found in []", "'fixture-item' not found in ['private']", "'fixture-item' not found in __import__('os')", "'fixture-item' not found in [] : private message"):
            self.assertNotIn('membership',extract_trace(self.root,self.hashes,prefix+suffix+'\n')['anchors'][0])
