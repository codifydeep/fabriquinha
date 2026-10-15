import json
import tempfile
from pathlib import Path
import unittest
from calibration_response_observations import describe,record
from deterministic_read_dispatch import ledger


class ParseObservationTests(unittest.TestCase):
    def test_content_tool_and_outer_errors_are_distinguished_without_raw_values(self):
        for data,phase in ((b'PRIVATE','outer_json'),
                (json.dumps(dict(choices=[dict(finish_reason='stop',message=dict(content='PRIVATE'))])).encode(),'terminal_content_json'),
                (json.dumps(dict(choices=[dict(finish_reason='tool_calls',message=dict(tool_calls=[dict(function=dict(arguments='PRIVATE'))]))])).encode(),'tool_arguments_json')):
            r=describe(data,'application/json');self.assertEqual(r['phase'],phase)
            self.assertNotIn('PRIVATE',json.dumps(r));self.assertIsNotNone(r['json_error'])
            self.assertFalse(r['response_forwarded']);self.assertFalse(r['delivery_approval'])

    def test_stream_frame_error_and_valid_json_are_not_execution_evidence(self):
        self.assertEqual(describe(b'data: PRIVATE\n\n','text/event-stream')['phase'],'stream_frame_json')
        data=json.dumps(dict(choices=[dict(finish_reason='stop',message=dict(content='{}'))])).encode()
        self.assertEqual(describe(data,'application/json')['phase'],'json_parsed')

    def test_receipt_survives_reopen_and_duplicate_is_idempotent(self):
        execution='00000000-0000-4000-8000-000000000001'
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'calls.json';path.write_text('{"calls":1}')
            for _ in range(2):record(str(path),execution,1,b'PRIVATE','application/json')
            with ledger(str(path)) as c:self.assertEqual(c.execute('SELECT count(*) FROM calibration_response_observations').fetchone()[0],1)
            with self.assertRaises(ValueError):record(str(path),execution,1,b'OTHER','application/json')
