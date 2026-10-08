import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import artifact_rejection_receipts as r
from broker.artifact_rejection_evidence import decode_logs
from portable_supervisor import stale_artifact_diagnosis_blocker

EXEC='eb720780-398c-4809-aa34-8c4848b279bf'

class RejectionReceiptTests(unittest.TestCase):
    def setUp(self):
        self.event=dict(event='model_proxy_request',status=502,execution_id=EXEC,
            call_number=4391,artifact_selected_tool='write_file',artifact_contract_present=True,
            artifact_rejection_category='artifact_test_methods_missing',private_payload='must not persist')

    def test_no_payload_or_execution_authority(self):
        receipt=r.from_event(self.event)
        self.assertNotIn('private_payload',receipt)
        for flag in ('write_executed','tests_executed','red_verified','delivery_approval'):
            self.assertIs(receipt[flag],False)

    def test_forced_patch_receipt_does_not_invent_legacy_shape(self):
        event=dict(self.event,artifact_selected_tool='patch',artifact_rejection_category='incomplete_forced_tool_response')
        receipt=r.from_event(event)
        self.assertEqual(receipt['operation'],'rejected_forced_tool_response_v1')
        self.assertEqual(receipt['tool'],'patch');self.assertNotIn('structure',receipt)
        self.assertNotIn('private_payload',receipt);self.assertIs(receipt['write_executed'],False)
        with tempfile.TemporaryDirectory() as folder:
            counter=Path(folder)/'calls.json';counter.write_text('{"calls":0}')
            r.record(counter,event);r.record(counter,event);self.assertEqual(r.read(counter,EXEC),[receipt])

    def test_forced_patch_shape_cannot_store_payload_or_unbounded_counts(self):
        shape=dict(schema='forced-tool-shape-v1',response_sha256='a'*64,streaming=True,
            stream_complete=True,finish_reason='tool_calls',tool_calls=2,all_selected_tools=True)
        event=dict(self.event,artifact_selected_tool='patch',artifact_rejection_category='incomplete_forced_tool_response',
            artifact_rejection_diagnostic=shape)
        self.assertEqual(r.from_event(event)['structure'],shape)
        for changed in (dict(source='PRIVATE'),dict(tool_calls=1000),dict(stream_complete=1)):
            with self.assertRaises(ValueError):r.from_event(dict(event,artifact_rejection_diagnostic=dict(shape,**changed)))

    def test_forced_read_rejection_preserves_shape_without_tool_execution_authority(self):
        shape=dict(schema='forced-tool-shape-v1',response_sha256='a'*64,streaming=True,
            stream_complete=True,finish_reason='tool_calls',tool_calls=8,all_selected_tools=True)
        receipt=r.from_event(dict(self.event,artifact_selected_tool='read_file',
            artifact_rejection_category='incomplete_forced_tool_response',artifact_rejection_diagnostic=shape))
        self.assertEqual(receipt['tool'],'read_file');self.assertEqual(receipt['structure'],shape)
        self.assertFalse(receipt['write_executed']);self.assertFalse(receipt['delivery_approval'])
        self.assertNotIn('private_payload',receipt)

    def test_unrelated_rejections_are_not_test_diagnostics(self):
        for key,value in [('status',200),('artifact_selected_tool','read_file'),
                          ('artifact_contract_present',False),('artifact_rejection_category','unknown')]:
            self.assertIsNone(r.from_event(dict(self.event,**{key:value})))

    def test_structural_diagnostic_is_bounded_and_contains_no_source(self):
        from artifact_response_contract import transport_structure
        structure=transport_structure('import unittest\\n')
        receipt=r.from_event(dict(self.event,artifact_rejection_diagnostic=structure))
        self.assertEqual(receipt['structure']['escaped_newlines'],1)
        with self.assertRaises(ValueError):r.from_event(dict(self.event,artifact_rejection_diagnostic=dict(structure,source='secret')))

    def test_durable_receipt_exact_execution_and_dedup(self):
        with tempfile.TemporaryDirectory() as folder:
            counter=str(Path(folder).resolve()/'calls.json')
            Path(counter).write_text('{"calls":0}')
            r.record(counter,self.event);r.record(counter,self.event)
            self.assertEqual(r.read(counter,EXEC),[r.from_event(self.event)])
            self.assertEqual(r.read(counter,'11111111-1111-4111-8111-111111111111'),[])

    def test_framed_logs_bounded_parser_rejects_truncation(self):
        raw=b'{"a":1}\n';frame=b'\x01\x00\x00\x00'+len(raw).to_bytes(4,'big')+raw
        self.assertEqual(decode_logs(frame),['{"a":1}'])
        with self.assertRaises(ValueError):decode_logs(frame[:-1])

    def test_projection_refresh_requires_same_diagnostic_not_terminal(self):
        diagnostic=dict(r.from_event(self.event),kind='rejected_test_write',issue_id='issue',task_id='source')
        proof=dict(author_retry_authorized=False,delivery_approval=False,
                   diagnostic_sha256=hashlib.sha256(json.dumps(diagnostic,sort_keys=True).encode()).hexdigest())
        managed=dict(route=dict(enabled=True,issue_id='issue'),state=dict(stage='test_first_cto_diagnosis',
            source_task='source',data=json.dumps(dict(diagnostic=diagnostic,artifact_diagnosis_replay=proof))))
        status=dict(stage='escalation_required',issue_id='issue',category='test_first_blocked:test_first_cto_requires_replanning')
        self.assertTrue(stale_artifact_diagnosis_blocker(status,managed))
        managed['state']['stage']='test_first_blocked'
        self.assertFalse(stale_artifact_diagnosis_blocker(status,managed))
