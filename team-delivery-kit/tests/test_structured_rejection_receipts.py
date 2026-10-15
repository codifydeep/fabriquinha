import json
import tempfile
import unittest
from pathlib import Path
import structured_rejection_receipts as receipts
from calibration_response_contract import context,capsule
from decision_schema import apply
from structured_response_contract import validate,StructuredResponseRejected

EXECUTION='9135f8fd-924a-4d15-87c0-addf0418f484'


class StructuredRejectionTests(unittest.TestCase):
    def test_versioned_transport_code_is_durable_but_arbitrary_reason_is_forbidden(self):
        event=self.event();event['structured_rejection_diagnostic'].update(
            version='calibration-constraint-v2',category='invalid_transport_or_tool',failure_code='stream_after_finish')
        with tempfile.TemporaryDirectory() as root:
            counter=str(Path(root).resolve()/'calls.json');Path(counter).write_text('{"calls":0}')
            receipts.record(counter,event);receipts.record(counter,event)
            self.assertEqual(receipts.read(counter,EXECUTION)[0]['diagnostic'],event['structured_rejection_diagnostic'])
            event['structured_rejection_diagnostic']['failure_code']='secret upstream detail'
            with self.assertRaises(ValueError):receipts.record(counter,event)
            event['structured_rejection_diagnostic']['failure_code']='schema_violation'
            with self.assertRaises(ValueError):receipts.from_event(event)

    def test_other_receipt_families_and_unbound_legacy_errors_are_not_reclassified(self):
        event=self.event()
        self.assertIsNone(receipts.from_event({**event,'structured_rejection_category':'typed_format_feedback_consumed','call_number':None}))
        self.assertIsNone(receipts.from_event({**event,'execution_id':None}))

    def event(self):
        return dict(event='model_proxy_request',status=502,category='structured_decision_response_invalid',
            execution_id=EXECUTION,call_number=1,structured_rejection_category='calibration_response_invalid',
            structured_rejection_diagnostic=dict(version='calibration-constraint-v1',category='schema_violation',
                constraints=['required'],fields=['modules'],missing_fields=['product_path'],upstream_sha256='a'*64))

    def test_durable_rejection_is_idempotent_and_cannot_grant_authority(self):
        with tempfile.TemporaryDirectory() as root:
            counter=str(Path(root).resolve()/'calls.json');event=self.event()
            Path(counter).write_text('{"calls":0}')
            receipts.record(counter,event);receipts.record(counter,event)
            stored=receipts.read(counter,EXECUTION)
            self.assertEqual(stored,[receipts.from_event(event)])
            self.assertFalse(stored[0]['response_forwarded']);self.assertFalse(stored[0]['worker_tool_executed'])
            self.assertFalse(stored[0]['delivery_approval']);self.assertFalse(stored[0]['execution_authorized'])
            with self.assertRaises(ValueError):receipts.record(counter,{**event,'structured_rejection_diagnostic':None})

    def test_arbitrary_messages_and_paths_are_never_persisted(self):
        for key,value in (('fields',['private-secret']),('missing_fields',['/secret/key']),('constraints',['rejected-value'])):
            event=self.event();event['structured_rejection_diagnostic'][key]=value
            with self.assertRaises(ValueError):receipts.from_event(event)
        event=self.event();event['structured_rejection_diagnostic']['message']='upstream text'
        with self.assertRaises(ValueError):receipts.from_event(event)

    def test_multipath_rejection_fields_are_durable_without_authority(self):
        with tempfile.TemporaryDirectory() as root:
            counter=str(Path(root).resolve()/'calls.json')
            Path(counter).write_text('{"calls":0}')
            event=self.event()
            event['structured_rejection_diagnostic']['fields']=['attribute','fixtures','replacements']
            event['structured_rejection_diagnostic']['missing_fields']=['attribute']
            receipts.record(counter,event)
            stored=receipts.read(counter,EXECUTION)
            self.assertEqual(stored[0]['diagnostic'],event['structured_rejection_diagnostic'])
            self.assertFalse(stored[0]['execution_authorized'])
            self.assertFalse(stored[0]['delivery_approval'])

    def test_current_bundle_schema_failure_exposes_only_known_fields_and_keywords(self):
        from test_calibration_response_contract import CalibrationContractTests
        fixture=CalibrationContractTests();body=apply(fixture.body(complete=True))
        raw=json.dumps(dict(choices=[dict(finish_reason='stop',message=dict(content=json.dumps(
            dict(action='propose_calibration_bundle',controls={'private-secret':'NEVER_PRINT_ME'}))))])).encode()
        with self.assertRaises(StructuredResponseRejected) as caught:validate(body,raw,'application/json')
        diagnostic=caught.exception.diagnostic
        self.assertEqual(diagnostic['category'],'schema_violation')
        self.assertIn('required',diagnostic['constraints']);self.assertIn('engine',diagnostic['missing_fields'])
        self.assertNotIn('private-secret',json.dumps(diagnostic));self.assertNotIn('NEVER_PRINT_ME',json.dumps(diagnostic))
        event=self.event();event['structured_rejection_diagnostic']=diagnostic
        self.assertIsNotNone(receipts.from_event(event))

    def test_nonjson_response_is_hashed_not_stored(self):
        from test_calibration_response_contract import CalibrationContractTests
        body=apply(CalibrationContractTests().body(complete=True))
        raw=json.dumps(dict(choices=[dict(finish_reason='stop',message=dict(content='private explanation'))])).encode()
        with self.assertRaises(StructuredResponseRejected) as caught:validate(body,raw,'application/json')
        self.assertEqual(caught.exception.diagnostic['category'],'invalid_json')
        self.assertNotIn('private explanation',json.dumps(caught.exception.diagnostic))
