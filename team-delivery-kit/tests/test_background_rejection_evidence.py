import json
import unittest
import sqlite3
from unittest.mock import patch
import service_mode_background_qualification as background
import service_mode_harness_qualification as calibration
from broker import harness_qualification as jobs


class BackgroundRejectionEvidenceTests(unittest.TestCase):
    def test_background_and_negative_counts_are_retained_without_private_fields(self):
        con=sqlite3.connect(':memory:');self.addCleanup(con.close)
        con.execute('CREATE TABLE delivery_routes(issue_id TEXT,config TEXT)')
        con.execute('INSERT INTO delivery_routes VALUES(?,?)',('issue',json.dumps({'cto':'cto'})))
        info=dict(Id='job',Config={'Labels':{'delivery-kit.harness-manifest':'a'*64}})
        counts=dict(tests=17,failures=1,errors=0,skipped=0,unexpected_successes=0,expected_failures=0,
            private_text='SECRET',output_sha256='c'*64)
        case=next(iter(calibration.CASES))
        raw=json.dumps(dict(status='rejected',phase='background_control',delivery_approval=False,
            facts=dict(manifest_sha256='a'*64,test_sha256='b'*64,positive=counts,
                background=counts,negative_controls={case:counts})))
        state=jobs.rejection_state(con,'issue',info,raw)
        self.assertEqual(state['diagnostic']['phase'],'background_control')
        self.assertEqual(state['diagnostic']['background']['failures'],1)
        self.assertIn(case,state['diagnostic']['negative_controls'])
        self.assertNotIn('SECRET',json.dumps(state))
        self.assertFalse(state['delivery_approval'])
    def test_controller_rejection_keeps_phase_and_immutable_evidence(self):
        facts=dict(manifest_sha256='a'*64,test_sha256='b'*64,
            positive=dict(tests=17,failures=1,errors=0,skipped=0))
        error=calibration.CalibrationRejected('positive_reference',facts)
        receipt=background.rejection(error)
        self.assertEqual(receipt['phase'],'positive_reference')
        self.assertEqual(receipt['facts'],facts)
        self.assertFalse(receipt['delivery_approval'])

    def test_unknown_exception_text_is_not_copied(self):
        receipt=background.rejection(ValueError('PRIVATE_MODEL_OR_CREDENTIAL_TEXT'))
        self.assertEqual(receipt,dict(status='rejected',category='ValueError',delivery_approval=False))
        self.assertNotIn('PRIVATE',json.dumps(receipt))

    def test_background_failure_cannot_be_reported_as_success(self):
        with self.assertRaises(ValueError):
            background.validate(dict(tests=17,failures=1,errors=0,skipped=0,
                unexpected_successes=0,expected_failures=0),dict(tests=17))
        facts=dict(manifest_sha256='a'*64,test_sha256='b'*64,background={'failures':1})
        result=background.rejection(calibration.CalibrationRejected('background_control',facts))
        self.assertEqual(result['phase'],'background_control')
        self.assertFalse(result['delivery_approval'])

    def test_original_controller_exception_propagates_without_loss(self):
        facts=dict(manifest_sha256='a'*64,test_sha256='b'*64)
        original=calibration.CalibrationRejected('behavioral_controls',facts)
        with patch.object(background.calibration,'run',side_effect=original):
            with self.assertRaises(calibration.CalibrationRejected) as caught:
                background.run('/unused','a'*64)
        self.assertIs(caught.exception,original)
        self.assertEqual(background.rejection(caught.exception)['facts'],facts)
