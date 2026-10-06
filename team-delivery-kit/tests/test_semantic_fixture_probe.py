import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import sys
from broker import assertion_witness

with patch.dict(sys.modules, {'assertion_witness': assertion_witness}):
    from broker.semantic_fixture_probe import calculate, calculate_scope


class SemanticFixtureTests(unittest.TestCase):
    def test_scoped_candidate_rejects_old_and_new_accentless_assertions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'tests').mkdir()
            path = 'tests/test_new.py'
            source = """class Tests:
    def test_unicode(self):
        self.create('Σίσυφος task')
        self.assertEqual(self.search('σισυφος'), ['Σίσυφος task'])
        self.assertEqual(self.search('ΣΊΣΥΦΟΣ'), ['Σίσυφος task'])
        self.assertEqual(self.search('ΣΙΣΥΦΟΣ'), ['Σίσυφος task'])
"""
            def check(text):
                (root / path).write_text(text)
                digest = hashlib.sha256(text.encode()).hexdigest()
                (root / 'manifest.json').write_text(json.dumps({'files': {path: {'sha256': digest}}}))
                return calculate_scope(root, {path: digest}, [{'file': path,
                    'test': 'tests.test_new.Tests.test_unicode', 'title': 'Σίσυφος task'}])
            failed = check(source)
            self.assertEqual([f['query_line'] for f in failed['contradictions']], [4, 6])
            fixed = source.replace("self.search('σισυφος'), ['Σίσυφος task']", "self.search('σισυφος'), []")
            fixed = fixed.replace("self.search('ΣΙΣΥΦΟΣ'), ['Σίσυφος task']", "self.search('ΣΙΣΥΦΟΣ'), []")
            self.assertEqual(check(fixed)['contradictions'], [])
            with self.assertRaises(ValueError):
                check(fixed.replace("self.create('Σίσυφος task')", "self.create('Σισυφος task')"))
            with self.assertRaises(ValueError):
                check(fixed.replace('self.search(', 'self.other_search('))
    def test_python_string_facts_come_from_hash_verified_source_not_llm(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'tests').mkdir()
            source = """class Tests:
    def test_substring(self):
        title = 'prefix-middle-suffix'
        self.assertEqual(self.search('fix'), [])
    def test_unicode(self):
        title = 'Σίσυφος task'
        self.assertEqual(self.search('σισυφος'), ['Σίσυφος task'])
        self.assertEqual(self.search('Σίσυφος'), ['Σίσυφος task'])
"""
            path = 'tests/test_new.py'
            (root / path).write_text(source)
            digest = hashlib.sha256(source.encode()).hexdigest()
            (root / 'manifest.json').write_text(json.dumps({'files': {path: {'sha256': digest}}}))
            output = ('FAIL: test_substring (tests.test_new.Tests.test_substring)\n'
                      "AssertionError: Lists differ: ['prefix-middle-suffix'] != []\n"
                      'FAIL: test_unicode (tests.test_new.Tests.test_unicode)\n'
                      "AssertionError: Lists differ: [] != ['Σίσυφος task']\n")
            proof = calculate(root, {path: digest}, output)
            self.assertEqual([fact['casefold_substring'] for fact in proof['facts']], [True, False, True])
            self.assertEqual(proof['facts'][0]['query_line'], 4)
            self.assertEqual(proof['status'], 'experiment_only_not_green_or_approval')
            self.assertEqual([f['query_line'] for f in proof['contradictions']], [4, 7])
            self.assertEqual([f['asserted_match'] for f in proof['contradictions']], [False, True])
