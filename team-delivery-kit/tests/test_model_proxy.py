import unittest
import json
from pathlib import Path
import tempfile
from unittest.mock import patch

import model_proxy
from model_proxy import MODEL, validate_request


class ModelProxyTests(unittest.TestCase):
    def test_http_403_blocks_next_forward_without_spending_another_call(self):
        from io import BytesIO
        from upstream_error_diagnostic import UpstreamRequestRejected
        body=json.dumps({'model':MODEL,'messages':[{'role':'user','content':'fixture'}]}).encode()
        def request():
            handler=object.__new__(model_proxy.Handler);handler.path='/api/v1/chat/completions'
            handler.headers={'Content-Length':str(len(body)),'Authorization':model_proxy.PLACEHOLDER}
            handler.rfile,handler.wfile=BytesIO(body),BytesIO()
            handler.send_response=lambda value:setattr(handler,'test_status',value)
            handler.send_header=lambda *args:None;handler.end_headers=lambda:None
            return handler
        with patch.object(model_proxy,'COUNTER_PATH',None),patch.object(model_proxy,'CALLS',0), \
                patch.object(model_proxy,'MAX_CALLS',10),patch.object(model_proxy,'PROVIDER_PAUSE',None), \
                patch.object(model_proxy,'forward',side_effect=UpstreamRequestRejected(
                    b'{"error":{"message":"PRIVATE credit limit exhausted"}}',status=403)) as forward:
            first,second=request(),request();first.do_POST();second.do_POST()
            self.assertEqual(first.test_status,403);self.assertEqual(second.test_status,403)
            self.assertIn(b'upstream_access_paused',second.wfile.getvalue())
            self.assertNotIn(b'PRIVATE',first.wfile.getvalue())
            forward.assert_called_once();self.assertEqual(model_proxy.CALLS,1)

    def test_access_pause_survives_restart_and_cannot_raise_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'calls.json';path.write_text('{"calls":7}')
            with patch.object(model_proxy,'COUNTER_PATH',str(path)),patch.object(model_proxy,'CALLS',7), \
                    patch.object(model_proxy,'PROVIDER_PAUSE',None):
                receipt=model_proxy.pause_provider(7,status=403)
                self.assertEqual(receipt['category'],'upstream_access_denied')
                with patch.object(model_proxy,'PROVIDER_PAUSE',None):
                    self.assertEqual(model_proxy.provider_pause(),receipt)
                    with self.assertRaisesRegex(ValueError,'access paused'):model_proxy.reserve_call()
                self.assertEqual(model_proxy.load_calls(),7)

    def test_budget_status_shape_is_unchanged_and_runtime_has_separate_endpoint(self):
        from io import BytesIO
        for path, keys in (('/status', {'calls', 'max_calls', 'remaining'}),
                           ('/runtime-status', {'response_deadline_seconds', 'runtime_decision_contract'})):
            handler = object.__new__(model_proxy.Handler)
            handler.path = path; handler.wfile = BytesIO()
            handler.send_response = lambda *a: None
            handler.send_header = lambda *a: None
            handler.end_headers = lambda: None
            handler.do_GET()
            self.assertEqual(set(json.loads(handler.wfile.getvalue())), keys)

    def test_correlated_route_accepts_only_exact_identity_and_endpoint(self):
        path = '/executions/12345678-1234-1234-1234-123456789abc/api/v1/chat/completions'
        self.assertEqual(model_proxy.execution_route(path), ('/api/v1/chat/completions', '12345678-1234-1234-1234-123456789abc'))
        for bad in (path+'?token=secret', path.replace('12345678', '../secret'), path.replace('chat/completions', 'messages')):
            self.assertEqual(model_proxy.execution_route(bad), (bad, None))
    def test_real_http_response_eof_does_not_require_a_closed_socket(self):
        from io import BytesIO
        from types import SimpleNamespace
        from unittest.mock import Mock
        wire = BytesIO(b'HTTP/1.1 200 OK\r\nContent-Length: 4\r\nConnection: close\r\n\r\nabcd')
        response = model_proxy.http.client.HTTPResponse(SimpleNamespace(makefile=lambda *a: wire))
        response.begin()
        with patch.object(model_proxy.time, 'monotonic', return_value=0):
            self.assertEqual(model_proxy.read_bounded_response(response,
                              SimpleNamespace(sock=Mock()), 10), b'abcd')
        self.assertTrue(response.isclosed())

    def test_slow_stream_cannot_extend_total_response_deadline(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        response = SimpleNamespace(fp=None, read1=Mock(return_value=b'keepalive'))
        sock = Mock()
        with patch.object(model_proxy.time, 'monotonic', side_effect=[0, 1, 2, 3, 4]):
            with self.assertRaisesRegex(TimeoutError, 'deadline'):
                model_proxy.read_bounded_response(response, SimpleNamespace(sock=sock), 3)
        self.assertEqual(response.read1.call_count, 2)
        self.assertEqual(sock.settimeout.call_args_list[0].args, (3,))

    def test_reader_handles_connection_close_socket_and_complete_body(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        sock = Mock()
        response = SimpleNamespace(fp=SimpleNamespace(raw=SimpleNamespace(_sock=sock)),
                                   read1=Mock(side_effect=[b'ab', b'cd', b'']))
        with patch.object(model_proxy.time, 'monotonic', return_value=0):
            self.assertEqual(model_proxy.read_bounded_response(response,
                              SimpleNamespace(sock=None), 10), b'abcd')

    def test_reader_never_returns_oversized_partial_response(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        response = SimpleNamespace(fp=None, read1=Mock(return_value=b'12345'))
        with patch.object(model_proxy, 'MAX_RESPONSE', 4), \
                patch.object(model_proxy.time, 'monotonic', return_value=0):
            with self.assertRaisesRegex(RuntimeError, 'too large'):
                model_proxy.read_bounded_response(response, SimpleNamespace(sock=Mock()), 10)

    def test_http_402_blocks_next_forward_without_charging_a_local_call(self):
        from io import BytesIO
        body = json.dumps({'model': MODEL, 'messages': [{'role': 'user', 'content': 'fixture'}]}).encode()
        def request():
            handler = object.__new__(model_proxy.Handler)
            handler.path = '/api/v1/chat/completions'
            handler.headers = {'Content-Length': str(len(body)), 'Authorization': model_proxy.PLACEHOLDER}
            handler.rfile, handler.wfile = BytesIO(body), BytesIO()
            handler.send_response = lambda value: setattr(handler, 'test_status', value)
            handler.send_header = lambda *args: None
            handler.end_headers = lambda: None
            return handler
        with patch.object(model_proxy, 'COUNTER_PATH', None), \
                patch.object(model_proxy, 'CALLS', 0), \
                patch.object(model_proxy, 'MAX_CALLS', 10), \
                patch.object(model_proxy, 'PROVIDER_PAUSE', None), \
                patch.object(model_proxy, 'forward', return_value=(402, b'{}', 'application/json')) as forward:
            first, second = request(), request()
            first.do_POST()
            second.do_POST()
            self.assertEqual(first.test_status, 402)
            self.assertEqual(second.test_status, 402)
            self.assertIn(b'upstream_payment_paused', second.wfile.getvalue())
            forward.assert_called_once()
            self.assertEqual(model_proxy.CALLS, 1)

    def test_payment_pause_survives_restart_without_reserving_another_call(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'calls.json'
            path.write_text('{"calls":1859}')
            with patch.object(model_proxy, 'COUNTER_PATH', str(path)), \
                    patch.object(model_proxy, 'CALLS', 1859), \
                    patch.object(model_proxy, 'PROVIDER_PAUSE', None):
                receipt = model_proxy.pause_provider(1859)
                self.assertEqual(receipt['upstream_status'], 402)
                with patch.object(model_proxy, 'PROVIDER_PAUSE', None):
                    self.assertEqual(model_proxy.provider_pause(), receipt)
                    with self.assertRaisesRegex(ValueError, 'payment paused'):
                        model_proxy.reserve_call()
                self.assertEqual(model_proxy.CALLS, 1859)
                self.assertEqual(model_proxy.load_calls(), 1859)

    def test_malformed_payment_receipt_cannot_silently_resume(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(model_proxy, 'COUNTER_PATH', str(Path(directory) / 'calls.json')):
            (Path(directory) / 'provider-pause.json').write_text('{"category":"unknown"}')
            with self.assertRaisesRegex(RuntimeError, 'invalid provider pause'):
                model_proxy.reserve_call()

    def test_controller_can_pin_nonmandatory_reasoning_disabled(self):
        for settings in ({}, {'reasoning_effort': 'high'},
                         {'reasoning': {'enabled': True, 'effort': 'max', 'max_tokens': 8192}}):
            with patch.object(model_proxy, 'REASONING_EFFORT', 'disabled'):
                body = validate_request({'model': MODEL, 'messages': [{}], **settings})
            self.assertEqual(body['reasoning'], {'enabled': False})
            self.assertNotIn('reasoning_effort', body)
            self.assertEqual(body['model'], MODEL)

    def test_native_reasoning_off_recovery_is_not_reenabled(self):
        for settings in ({'reasoning': {'enabled': False, 'effort': 'none'}},
                         {'reasoning_effort': 'none'},
                         {'reasoning': {'effort': 'none'}}):
            with patch.object(model_proxy, 'REASONING_EFFORT', 'low'):
                body = validate_request({'model': MODEL, 'messages': [{}], **settings})
            self.assertEqual(body['reasoning'], {'enabled': False})
            self.assertEqual(model_proxy.safe_request_metrics(body)['reasoning_effort'], 'none')

    def test_controlled_low_reasoning_overrides_worker_settings(self):
        for settings in ({}, {'reasoning_effort': 'high'},
                         {'reasoning': {'effort': 'max', 'max_tokens': 8192,
                                        'exclude': True}, 'include_reasoning': False}):
            body = {'model': MODEL, 'messages': [{'role': 'user', 'content': 'probe'}],
                    **settings}
            with patch.object(model_proxy, 'REASONING_EFFORT', 'low'):
                validated = validate_request(body)
            self.assertEqual(validated['reasoning'], {'effort': 'low'})
            self.assertNotIn('reasoning_effort', validated)
            self.assertNotIn('include_reasoning', validated)
            self.assertEqual(validated['model'], MODEL)

    def test_route_metrics_never_expose_arbitrary_paths_or_queries(self):
        self.assertEqual(model_proxy.safe_route_label('/api/v1/responses'), '/api/v1/responses')
        for path in ('/api/v1/chat/completions?key=secret', '/private/secret', '/unknown'):
            self.assertEqual(model_proxy.safe_route_label(path), 'unrecognized_route')

    def test_safe_metrics_do_not_include_message_content(self):
        body = {'model': MODEL, 'messages': [{'role': 'user', 'content': 'secret'}],
                'max_tokens': 4096, 'reasoning': {'effort': 'low'}}
        metrics = model_proxy.safe_request_metrics(body)
        self.assertEqual(metrics, {'artifact_contract_present': False, 'artifact_selected_tool': None,
            'output_limit': 4096, 'reasoning_effort': 'low',
            'structured_format': None, 'decision_schema': None, 'strict_schema': False,
            'require_parameters': False, 'tool_count': 0})
        self.assertNotIn('secret', json.dumps(metrics))
        data = (b'data: {"choices":[{"delta":{"content":"private"},"finish_reason":"length"}]}\n'
                b'data: {"choices":[],"usage":{"completion_tokens":4096,'
                b'"completion_tokens_details":{"reasoning_tokens":4096}}}\n')
        response = model_proxy.safe_response_metrics(data, 'text/event-stream')
        self.assertEqual(response, {'finish_reason': 'length', 'completion_tokens': 4096,
                                    'reasoning_tokens': 4096})
        self.assertNotIn('private', json.dumps(response))

    def test_durable_counter_survives_restart_and_enforces_cap(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'calls.json'
            path.write_text('{"calls":45}')
            with patch.object(model_proxy, 'COUNTER_PATH', str(path)), \
                    patch.object(model_proxy, 'CALLS', 45), \
                    patch.object(model_proxy, 'MAX_CALLS', 46):
                self.assertEqual(model_proxy.reserve_call(), 46)
                self.assertEqual(json.loads(path.read_text()), {'calls': 46})
                self.assertEqual(model_proxy.load_calls(), 46)
                with self.assertRaisesRegex(ValueError, 'limit reached'):
                    model_proxy.reserve_call()
    def test_only_selected_model_and_bounded_nonstreaming_request(self):
        valid = {'model': MODEL, 'messages': [{'role': 'user', 'content': 'probe'}]}
        self.assertEqual(validate_request(valid)['max_tokens'], 2048)
        self.assertEqual(validate_request({**valid, 'stream': True, 'max_tokens': 4096})['max_tokens'], 2048)
        for invalid in ({**valid, 'model': 'other'}, {**valid, 'stream': 'true'},
                        {**valid, 'max_tokens': -1}, {**valid, 'messages': []}):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                validate_request(invalid)

    def test_isolated_output_budget_can_be_raised_without_changing_model(self):
        valid = {'model': MODEL, 'messages': [{'role': 'user', 'content': 'probe'}],
                 'max_tokens': 8192}
        with patch.object(model_proxy, 'MAX_OUTPUT_TOKENS', 4096):
            self.assertEqual(validate_request(dict(valid))['max_tokens'], 4096)
        with patch.object(model_proxy, 'MAX_OUTPUT_TOKENS', 8192):
            self.assertEqual(validate_request(dict(valid))['max_tokens'], 8192)


if __name__ == '__main__':
    unittest.main()
