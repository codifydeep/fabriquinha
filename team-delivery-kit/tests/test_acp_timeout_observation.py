import json
import threading
import unittest
from unittest.mock import patch
from broker.acp_transport import Transport,record_timeout


class ACPTimeoutObservationTests(unittest.TestCase):
    def test_receipt_is_durable_idempotent_and_does_not_store_frame(self):
        import sqlite3
        con=sqlite3.connect(':memory:');self.addCleanup(con.close)
        error=TimeoutError();error.transport_timeout_receipt=dict(execution_id='execution',retry_authorized=False,phase='bootstrap')
        frame=dict(method='initialize',params={'private':'SECRET'})
        self.assertTrue(record_timeout(con,'execution',frame,error))
        self.assertTrue(record_timeout(con,'execution',frame,error))
        rows=con.execute('SELECT * FROM acp_transport_failures').fetchall()
        self.assertEqual(len(rows),1)
        self.assertNotIn('SECRET',json.dumps(rows))
        with self.assertRaises(ValueError):record_timeout(con,'foreign',frame,error)
        error.transport_timeout_receipt['phase']='prompt'
        with self.assertRaises(ValueError):record_timeout(con,'execution',frame,error)

    def transport(self):
        value=object.__new__(Transport)
        value.lock=threading.Lock()
        value.execution_id='aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        value.stderr_tail=b'PRIVATE conversation and credential sample'
        return value

    def test_bootstrap_and_prompt_timeout_preserve_error_without_replay(self):
        for method,phase in (('initialize','bootstrap'),('session/new','bootstrap'),('session/prompt','prompt')):
            with self.subTest(method=method):
                transport=self.transport();original=TimeoutError('PRIVATE socket diagnostics')
                frame=dict(method=method,params={'private':'SECRET'})
                with patch.object(transport,'_exchange',side_effect=original) as exchange,patch('broker.acp_transport.time.monotonic',side_effect=[10,35]):
                    with self.assertRaises(TimeoutError) as caught:transport.exchange(frame)
                self.assertIs(caught.exception,original)
                receipt=original.transport_timeout_receipt
                self.assertEqual(receipt['method'],method)
                self.assertEqual(receipt['phase'],phase)
                self.assertEqual(receipt['elapsed_seconds'],25)
                self.assertFalse(receipt['retry_authorized'])
                self.assertFalse(receipt['approval'])
                self.assertNotIn('PRIVATE',json.dumps(receipt))
                self.assertNotIn('SECRET',json.dumps(receipt))
                self.assertEqual(exchange.call_count,1)
                self.assertFalse(transport.lock.locked())

    def test_success_and_non_timeout_are_not_classified_as_timeout(self):
        transport=self.transport()
        with patch.object(transport,'_exchange',return_value={'result':{}}):
            self.assertEqual(transport.exchange({'method':'initialize'}),{'result':{}})
        error=ValueError('contract rejection')
        with patch.object(transport,'_exchange',side_effect=error):
            with self.assertRaises(ValueError):transport.exchange({'method':'initialize'})
        self.assertFalse(hasattr(error,'transport_timeout_receipt'))
        self.assertFalse(transport.lock.locked())
