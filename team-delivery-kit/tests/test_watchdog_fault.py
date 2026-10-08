import unittest
from broker.watchdog_fault import describe


class WatchdogFaultTests(unittest.TestCase):
    def test_location_and_hash_without_message_or_locals(self):
        secret='synthetic-private-key-do-not-export'
        try:raise ValueError(secret)
        except ValueError as error:result=describe(error)
        self.assertEqual(result['error_type'],'ValueError')
        self.assertEqual(result['module'],'test_watchdog_fault.py')
        self.assertEqual(result['function'],'test_location_and_hash_without_message_or_locals')
        self.assertIsInstance(result['line'],int)
        self.assertEqual(len(result['error_sha256']),64)
        self.assertNotIn(secret,str(result))
        self.assertFalse(result['delivery_approval'])

    def test_unraised_exception_has_no_invented_location(self):
        result=describe(RuntimeError('unobserved failure'))
        self.assertIsNone(result['module']);self.assertIsNone(result['line'])
