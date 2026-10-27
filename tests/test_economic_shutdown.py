import json
from pathlib import Path
import tempfile
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from fabriquinha.runtime import Runtime,Owner
from fabriquinha.effects import write_json
from test_provider import policy


class EconomicShutdown(unittest.TestCase):
    def test_pause_owner_and_drain_fence_policy_change_without_touching_meter(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);runtime=Runtime.__new__(Runtime);runtime.root=root
            value=policy();runtime.project=SimpleNamespace(fingerprint=lambda:value.project)
            runtime.control=Mock();runtime.control.read.return_value=dict(paused=True,error=None,episode='a'*32)
            runtime.pause_status=Mock(return_value=dict(drained=True))
            write_json(root/'provider-policy.json',value.values())
            write_json(root/'calls.json',dict(calls=6953));before=(root/'calls.json').read_bytes()
            api=Mock();api.connect_closing.return_value.__enter__=Mock(return_value=object())
            api.connect_closing.return_value.__exit__=Mock(return_value=False)
            with patch('fabriquinha.runtime.native',return_value=(None,api,None)):
                with self.assertRaises(ValueError):runtime.disable_provider('b'*32)
                runtime.pause_status.return_value=dict(drained=False)
                with self.assertRaises(ValueError):runtime.disable_provider('a'*32)
                self.assertEqual(json.loads((root/'provider-policy.json').read_bytes()),value.values())
                runtime.pause_status.return_value=dict(drained=True)
                with Owner(root),self.assertRaises(BlockingIOError):runtime.disable_provider('a'*32)
                result=runtime.disable_provider('a'*32)
                self.assertTrue(result['relay_stop_or_recreate_required'])
                self.assertEqual(json.loads((root/'provider-policy.json').read_bytes()),{**value.values(),'enabled':False})
                self.assertEqual((root/'calls.json').read_bytes(),before)
                self.assertTrue(runtime.disable_provider('a'*32)['already_disabled'])
