import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from broker.test_review_facts import compare, validate_findings


class TestReviewFactsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.old = 'class Cases:\n    def test_keep(self):\n        self.assertEqual(2, 2)\n'
        self.new = self.old + '    def test_add(self):\n        self.assertTrue(True)\n'

    def fixture(self, candidate=None, previous=None):
        selection = {}
        for name, text in (('candidate', candidate or self.new), ('previous', previous or self.old)):
            root = self.root / name; root.mkdir(exist_ok=True)
            data = text.encode(); sha = hashlib.sha256(data).hexdigest()
            (root / 'test_case.py').write_bytes(data)
            encoded = json.dumps({'files': {'test_case.py': {'sha256': sha, 'bytes': len(data)}}}).encode()
            (root / 'manifest.json').write_bytes(encoded)
            selection[name] = {'manifest_sha256': hashlib.sha256(encoded).hexdigest(), 'test_sha256': {'test_case.py': sha}}
        return compare(self.root / 'candidate', self.root / 'previous', selection), selection

    def finding(self, **overrides):
        return {**{'kind': 'missing_coverage', 'tree': 'candidate', 'path': 'test_case.py',
                'test': 'Cases.test_keep', 'line': 3, 'quote': 'self.assertEqual(2, 2)',
                'expected': 'Test a dynamic input.', 'observed': 'Only constants are compared.'}, **overrides}

    def validate(self, report, finding):
        return validate_findings({'action': 'reject_test_revision', 'findings': [finding]}, report)

    def test_inventory_preserves_methods_and_counts_without_semantic_approval(self):
        report, _ = self.fixture()
        facts = report['summary']['files']['test_case.py']
        self.assertEqual(facts['removed_methods'], [])
        self.assertEqual(facts['added_methods'], ['Cases.test_add'])
        self.assertEqual((facts['previous_assertions'], facts['candidate_assertions']), (1, 2))
        self.assertIn('not semantic', report['summary']['limitation'])
        self.assertEqual(self.validate(report, self.finding()), [self.finding()])

    def test_fabricated_method_line_quote_or_removal_is_rejected(self):
        report, _ = self.fixture()
        for override in ({'test': 'Cases.test_imaginary'}, {'line': 1}, {'quote': 'self.assertFalse(False)'},
                         {'kind': 'removed_method', 'tree': 'previous'},
                         {'kind': 'removed_assertion', 'tree': 'previous'}):
            with self.subTest(override=override), self.assertRaises(ValueError):
                self.validate(report, self.finding(**override))

    def test_real_removed_method_or_assertion_is_detected(self):
        report, _ = self.fixture(candidate=self.old, previous=self.new)
        self.validate(report, self.finding(kind='removed_method', tree='previous', test='Cases.test_add',
                                          line=5, quote='self.assertTrue(True)'))
        report, _ = self.fixture(candidate=self.old.replace('self.assertEqual(2, 2)', 'pass'))
        self.validate(report, self.finding(kind='removed_assertion', tree='previous'))

    def test_changed_assertion_message_is_not_evidence_of_deleted_assertion(self):
        old = self.old.replace('self.assertEqual(2, 2)', 'self.assertEqual(2, 2, "old diagnostic")')
        new = old.replace('old diagnostic', 'new diagnostic')
        report, _ = self.fixture(candidate=new, previous=old)
        self.assertTrue(report['summary']['files']['test_case.py']['removed_assertion_ast'])
        with self.assertRaisesRegex(ValueError, 'removed assertion contradicted'):
            self.validate(report, self.finding(kind='removed_assertion', tree='previous', quote='self.assertEqual(2, 2,'))

    def test_tampering_and_empty_rejection_or_approval_with_findings_are_rejected(self):
        report, selection = self.fixture()
        (self.root / 'candidate' / 'test_case.py').write_text('pass')
        with self.assertRaisesRegex(ValueError, 'drift'):
            compare(self.root / 'candidate', self.root / 'previous', selection)
        with self.assertRaises(ValueError):
            validate_findings({'action': 'reject_test_revision', 'findings': []}, report)
        with self.assertRaises(ValueError):
            validate_findings({'action': 'approve_test_revision', 'findings': [self.finding()]}, report)
        self.assertEqual(validate_findings({'action': 'approve_test_revision', 'findings': []}, report), [])
