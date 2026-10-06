import unittest
from broker.capture_diagnosis import validate


class CaptureDiagnosisTests(unittest.TestCase):
    def setUp(self):
        self.path = 'tests/test_capture.py'
        self.report = {'witnesses': [{'path': self.path, 'capture': 'oldest',
            'whole': {'line': 2}, 'element': {'line': 3}}],
            'sources': {self.path: ['self.report = shared_report', 'expected_list', 'expected_last']}}
        self.reads = {'/evidence/candidate/' + self.path: {'lines': 3, 'total_lines': 3}}
        self.decision = {'action': 'request_test_revision', 'capture_resolutions': [{
            'path': self.path, 'capture': 'oldest', 'whole_line': 2, 'element_line': 3,
            'lifetime': 'shared', 'line': 1, 'quote': 'self.report = shared_report'}]}

    def test_shared_capture_allows_proposal_not_product_correction(self):
        proof = validate(self.decision, self.report, self.reads)
        self.assertEqual(proof['read_contract'], 'complete-lines-v2')
        self.decision['action'] = 'request_correction'
        with self.assertRaisesRegex(ValueError, 'product correction'):
            validate(self.decision, self.report, self.reads)

    def test_unknown_lifetime_requires_escalation(self):
        self.decision['capture_resolutions'][0]['lifetime'] = 'unknown'
        with self.assertRaises(ValueError):
            validate(self.decision, self.report, self.reads)
        self.decision['action'] = 'escalate_cto'
        validate(self.decision, self.report, self.reads)

    def test_incomplete_read_and_invented_source_are_rejected(self):
        for reads in ({}, {'/evidence/candidate/' + self.path: {'lines': 2, 'total_lines': 3}}):
            with self.assertRaisesRegex(ValueError, 'complete source'):
                validate(self.decision, self.report, reads)
        self.decision['capture_resolutions'][0]['quote'] = 'invented'
        with self.assertRaisesRegex(ValueError, 'not present'):
            validate(self.decision, self.report, self.reads)

    def test_wrong_witness_missing_resolution_and_distinct_claim_are_rejected(self):
        for key, value in (('capture', 'different'), ('whole_line', 200), ('lifetime', 'distinct')):
            original = self.decision['capture_resolutions'][0][key]
            self.decision['capture_resolutions'][0][key] = value
            with self.assertRaises(ValueError):
                validate(self.decision, self.report, self.reads)
            self.decision['capture_resolutions'][0][key] = original
        self.decision['capture_resolutions'] = []
        with self.assertRaises(ValueError):
            validate(self.decision, self.report, self.reads)
