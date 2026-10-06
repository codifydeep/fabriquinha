import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
from arm_controlled_worker_loss import arm

ISSUE='12345678-1234-1234-1234-123456789abc'
class ArmLossTests(unittest.TestCase):
    def test_verified_arm_before_assignment_and_no_second_dispatch(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve();run=Mock();read=Mock(return_value=json.dumps(dict(
                issue_id=ISSUE,operation='controlled_pretool_sigkill')))
            arm(root,'delivery-kit-port2',ISSUE,run,read)
            record=json.loads((root/'fault-injection'/(ISSUE+'.dispatch.json')).read_text())
            self.assertEqual(record['stage'],'armed');self.assertFalse(record['author_retry_authorized'])
            with self.assertRaisesRegex(ValueError,'already attempted'):arm(root,'delivery-kit-port2',ISSUE,run,read)
            run.assert_called_once();self.assertIn('-d',run.call_args.args[0])
    def test_uncertain_dispatch_is_never_blindly_repeated(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve();run=Mock(side_effect=TimeoutError('ack'))
            with self.assertRaises(TimeoutError):arm(root,'delivery-kit-port2',ISSUE,run,Mock())
            with self.assertRaisesRegex(ValueError,'already attempted'):arm(root,'delivery-kit-port2',ISSUE,run,Mock())
            run.assert_called_once()
