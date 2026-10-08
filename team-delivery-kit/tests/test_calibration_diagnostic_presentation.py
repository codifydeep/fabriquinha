import json
import unittest
from run_calibration_diagnostic import presentation


class CalibrationDiagnosticPresentationTests(unittest.TestCase):
    def test_measured_counts_and_hashes_are_not_approval(self):
        result=dict(container_id='job',exit_code=1,result=dict(status='rejected',phase='behavioral_controls',
            facts=dict(manifest_sha256='a'*64,test_sha256='b'*64,
                positive=dict(tests=15,failures=0,errors=0,skipped=0))))
        value=presentation(result,'task')
        self.assertEqual(value['positive']['tests'],15)
        self.assertEqual(value['phase'],'behavioral_controls')
        self.assertFalse(value['author_retry_authorized'])
        self.assertFalse(value['delivery_approval'])

    def test_unknown_fields_are_not_echoed(self):
        result=dict(container_id='job',exit_code=1,result=dict(status='SECRET',phase='SECRET',
            facts=dict(manifest_sha256='SECRET',test_sha256='SECRET',
                positive=dict(tests='SECRET',failures=-1,errors=True,skipped=10001))))
        value=presentation(result,'task')
        self.assertNotIn('SECRET',json.dumps(value))
        self.assertEqual(value['status'],'unknown')
        self.assertIsNone(value['phase'])
        self.assertTrue(all(v is None for v in value['positive'].values()))
