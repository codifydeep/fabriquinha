import os
import unittest
from unittest.mock import patch

from broker.install_controller_denial_message import OLD, adapt


class ControllerDenialMessageTests(unittest.TestCase):
    def test_denial_remains_denied_and_human_message_is_preserved(self):
        source = 'def decision(approval_callback, breaker_addendum):\n    return {"approved": False,"outcome":"denied", "message": (\n' + OLD + '    )}\n'
        namespace = {}
        exec(compile(adapt(source), '<denial-test>', 'exec'), namespace)
        with patch.dict(os.environ, {'HERMES_CONTROLLER_DENIAL_MESSAGES': '1'}):
            result = namespace['decision'](lambda: None, '')
            self.assertFalse(result['approved'])
            self.assertEqual(result['outcome'], 'denied')
            self.assertIn('Do NOT retry', result['message'])
            self.assertIn('already-permitted work', result['message'])
            self.assertIn('User denied', namespace['decision'](None, '')['message'])
        with patch.dict(os.environ, {'HERMES_CONTROLLER_DENIAL_MESSAGES': '0'}):
            self.assertIn('User denied', namespace['decision'](lambda: None, '')['message'])

    def test_installer_rejects_drift_and_double_patch(self):
        with self.assertRaises(ValueError):
            adapt('unknown source')
        with self.assertRaises(ValueError):
            adapt(adapt(OLD))
