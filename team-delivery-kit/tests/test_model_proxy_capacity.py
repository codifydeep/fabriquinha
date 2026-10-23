"""Bounded transport capacity is not a call-budget or delivery-gate waiver."""
from io import BytesIO
import json
import unittest
from unittest.mock import Mock,patch
import model_proxy as proxy


class ModelProxyCapacityTests(unittest.TestCase):
    def handler(self,raw,declared=None):
        h=object.__new__(proxy.Handler);h.path='/api/v1/chat/completions'
        h.headers={'Content-Length':str(len(raw) if declared is None else declared),
            'Authorization':proxy.PLACEHOLDER}
        h.rfile=BytesIO(raw);h.wfile=BytesIO()
        h.send_response=lambda status:setattr(h,'observed_status',status)
        h.send_header=lambda *a:None;h.end_headers=lambda:None
        return h

    def test_only_explicit_bounded_capacities_are_accepted_and_default_is_unchanged(self):
        self.assertEqual(proxy.request_body_limit({}),524288)
        for n in (524288,1048576,2097152):
            self.assertEqual(proxy.request_body_limit({'MODEL_PROXY_MAX_REQUEST_BYTES':str(n)}),n)
        for raw in ('0','-1','unlimited','2097153','4194304','1e6','1048576 ',True,1048576):
            with self.subTest(raw=raw),self.assertRaises(ValueError):
                proxy.request_body_limit({'MODEL_PROXY_MAX_REQUEST_BYTES':raw})

    def test_oversize_rejects_before_body_read_or_call_reservation_and_logs_sizes_only(self):
        h=self.handler(b'',proxy.MAX_BODY+1);h.rfile=Mock(side_effect=AssertionError('must not read'))
        with patch.object(proxy,'forward') as forward,patch.object(proxy,'CALLS',7), \
                patch.object(proxy,'reserve_call') as reserve,patch('builtins.print') as log:
            h.do_POST()
            self.assertEqual(proxy.CALLS,7)
        self.assertEqual(h.observed_status,400);h.rfile.read.assert_not_called()
        reserve.assert_not_called();forward.assert_not_called()
        event=json.loads(log.call_args.args[0])
        self.assertEqual(event['request_bytes'],proxy.MAX_BODY+1)
        self.assertEqual(event['max_request_bytes'],proxy.MAX_BODY)
        self.assertEqual(event['category'],'request body size limit')
        self.assertIsNone(event['call_number'])
        self.assertNotIn('Authorization',str(event));self.assertNotIn('messages',event)

    def test_explicit_capacity_accepts_large_review_without_increasing_call_ceiling(self):
        raw=json.dumps(dict(model=proxy.MODEL,messages=[dict(role='user',content='private-fixture-'+'x'*600000)])).encode()
        h=self.handler(raw)
        reply=json.dumps(dict(choices=[dict(message=dict(role='assistant',content='fixture'),finish_reason='stop')])).encode()
        with patch.object(proxy,'MAX_BODY',2097152),patch.object(proxy,'COUNTER_PATH',None), \
                patch.object(proxy,'CALLS',7),patch.object(proxy,'MAX_CALLS',10), \
                patch.object(proxy,'PROVIDER_PAUSE',None), \
                patch.object(proxy,'forward',return_value=(200,reply,'application/json')) as forward, \
                patch('builtins.print') as log:
            h.do_POST()
            self.assertEqual(proxy.CALLS,8);self.assertEqual(proxy.MAX_CALLS,10)
        self.assertEqual(h.observed_status,200);forward.assert_called_once()
        self.assertNotIn('private-fixture',str(log.call_args))

    def test_runtime_observation_exposes_limit_separately_from_call_budget(self):
        h=self.handler(b'');h.path='/runtime-status'
        with patch.object(proxy,'MAX_BODY',2097152):h.do_GET()
        self.assertEqual(json.loads(h.wfile.getvalue())['max_request_bytes'],2097152)


if __name__=='__main__':unittest.main()
