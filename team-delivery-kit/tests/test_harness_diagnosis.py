import copy
import unittest

from broker.handoffs import harness_diagnosis_instruction


class HarnessDiagnosisTests(unittest.TestCase):
    def setUp(self):
        self.route = {'test_first_files': ['tests/test_new.py']}
        self.data = {'source_task': 'author', 'validation_failure': {
            'category': 'executed_test_failure', 'output_sha256': 'a' * 64,
            'diagnostic_read_files': ['app/client.js']}, 'harness_diagnosis': {
            'source_task': 'author', 'output_sha256': 'a' * 64, 'approval': False,
            'file_sha256': {'tests/test_new.py': 'b' * 64, 'app/client.js': 'c' * 64},
            'findings': ['FIFO resolution contradicts the current-first driver.']}}

    def test_nonapproving_complete_bounded_context(self):
        note = harness_diagnosis_instruction(self.data, self.route)
        self.assertLessEqual(len(note) + 82, 4000)
        self.assertIn('NOT a decision or approval', note)
        self.assertIn('negative controls', note)
        self.assertIn('DELIVERY_REVIEW_READ_PATH:/evidence/candidate/tests/test_new.py', note)
        self.assertIn('DELIVERY_REVIEW_READ_PATH:/evidence/candidate/app/client.js', note)

    def test_rejects_obsolete_approving_or_incomplete_evidence(self):
        for field, value in [('source_task', 'other'), ('output_sha256', 'd' * 64),
                             ('approval', True), ('findings', []),
                             ('file_sha256', {'tests/test_new.py': 'b' * 64})]:
            with self.subTest(field=field):
                data = copy.deepcopy(self.data)
                data['harness_diagnosis'][field] = value
                with self.assertRaises(ValueError):
                    harness_diagnosis_instruction(data, self.route)

    def test_rejects_unbounded_findings(self):
        self.data['harness_diagnosis']['findings'] = ['x' * 501]
        with self.assertRaises(ValueError):
            harness_diagnosis_instruction(self.data, self.route)

    def test_admission_category_does_not_implicitly_waive_evidence(self):
        self.data['validation_failure']['category']='source_harness_admission_failure'
        with self.assertRaises(ValueError):
            harness_diagnosis_instruction(self.data,{**self.route,'issue_id':'issue'})
