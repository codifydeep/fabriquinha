import hashlib
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import model_proxy
import proxy_request_rejections as receipts

EXECUTION = '7af28c6e-1350-497f-8950-d39642f2ee58'


class RequestRejectionTests(unittest.TestCase):
    def receipt(self):
        return receipts.describe(ValueError('private secret and /private/path'),
            'contract', EXECUTION, 'a'*64)

    def test_diagnostic_never_exposes_exception_text_or_unknown_frame(self):
        result = self.receipt()
        encoded = json.dumps(result)
        self.assertNotIn('private', encoded)
        self.assertNotIn('secret', encoded)
        self.assertIsNone(result['origin'])
        self.assertFalse(result['retry_authorized'])
        self.assertFalse(result['delivery_approval'])

    def test_identity_and_stage_are_exact(self):
        for stage, execution, digest in [('other', EXECUTION, 'a'*64),
                ('contract', '../secret', 'a'*64), ('contract', EXECUTION, 'invalid')]:
            with self.assertRaises(ValueError):
                receipts.describe(ValueError('private'), stage, execution, digest)

    def test_durable_deduplicated_and_readonly_after_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            counter = Path(directory)/'calls.json'
            counter.write_text('{"calls":4735}')
            receipt = self.receipt()
            receipts.record(counter, receipt)
            receipts.record(counter, receipt)
            self.assertEqual(receipts.read(counter, EXECUTION), [receipt])
            self.assertEqual(json.loads(counter.read_text()), {'calls':4735})
            self.assertEqual(counter.with_name('request-rejections.sqlite').stat().st_mode & 0o777, 0o600)

    def test_symlink_ledger_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            counter = Path(directory)/'calls.json'
            counter.write_text('{}')
            target = Path(directory)/'outside'
            target.write_text('preserve')
            counter.with_name('request-rejections.sqlite').symlink_to(target)
            with self.assertRaises(ValueError): receipts.record(counter, self.receipt())
            self.assertEqual(target.read_text(), 'preserve')

    def test_receipt_cannot_store_payload_or_authorize_retries(self):
        for changed in ({'prompt':'private'}, {'retry_authorized':True},
                {'delivery_approval':True}, {'origin':{'module':'secret','line':1}}):
            with self.assertRaises(ValueError):
                receipts.record(None,{**self.receipt(),**changed})

    def test_http_preflight_failure_records_stage_without_spending_model_call(self):
        raw = json.dumps({'model':model_proxy.MODEL,
                         'messages':[{'role':'user','content':'private prompt'}]}).encode()
        handler = object.__new__(model_proxy.Handler)
        handler.path = '/executions/'+EXECUTION+'/api/v1/chat/completions'
        handler.headers = {'Authorization':model_proxy.PLACEHOLDER,'Content-Length':str(len(raw))}
        handler.rfile = BytesIO(raw); handler.wfile = BytesIO()
        statuses = []
        handler.send_response = statuses.append
        handler.send_header = lambda *a:None
        handler.end_headers = lambda:None
        with tempfile.TemporaryDirectory() as directory:
            counter = Path(directory)/'calls.json'; counter.write_text('{"calls":4735}')
            with patch.object(model_proxy,'COUNTER_PATH',str(counter)), \
                    patch.object(model_proxy,'validate_request',side_effect=ValueError('private credential')), \
                    patch.object(model_proxy,'forward') as forward, patch('builtins.print') as log:
                handler.do_POST()
            self.assertEqual(statuses,[400]); forward.assert_not_called()
            saved = receipts.read(counter,EXECUTION)
            self.assertEqual(saved[0]['stage'],'contract')
            self.assertEqual(saved[0]['request_sha256'],hashlib.sha256(raw).hexdigest())
            self.assertNotIn('private', str(log.call_args))
            self.assertEqual(json.loads(counter.read_text()),{'calls':4735})

    def test_http_rejection_receipt_failure_remains_fail_closed(self):
        raw = b'{"model":"wrong","messages":[]}'
        handler = object.__new__(model_proxy.Handler)
        handler.path = '/executions/'+EXECUTION+'/api/v1/chat/completions'
        handler.headers = {'Authorization':model_proxy.PLACEHOLDER,'Content-Length':str(len(raw))}
        handler.rfile = BytesIO(raw);handler.wfile = BytesIO()
        statuses=[];handler.send_response=statuses.append
        handler.send_header=lambda *a:None;handler.end_headers=lambda:None
        with patch.object(receipts,'record',side_effect=OSError('secret')),patch('builtins.print'):
            handler.do_POST()
        self.assertEqual(statuses,[503])
        self.assertEqual(json.loads(handler.wfile.getvalue())['error']['code'],
                         'request_rejection_receipt_unavailable')
