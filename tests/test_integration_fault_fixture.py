import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from qualify_hermes_integration import FixtureRuntime,Deployment,Pending,Runtime


class ComposeAcknowledgementFixture(unittest.TestCase):
    def test_loss_occurs_after_send_once_and_counts_any_resend(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'compose-ack-loss-enabled.json').write_text('{}')
            runtime=object.__new__(FixtureRuntime)
            runtime.root=root;runtime.project=NS(qualification=True)
            deployment=NS(service=lambda:{'container':'exact-created-container'})
            def worker(*args):
                return Deployment._command(deployment,root/'deployment-key','compose-output',
                    'compose','up','-d','web')
            with patch.object(Runtime,'worker',side_effect=worker),patch.object(Deployment,'_command',return_value='sent') as send:
                with self.assertRaises(Pending):runtime.worker('task',1)
                self.assertEqual(send.call_count,1)
                fault=json.loads((root/'compose-ack-lost.json').read_bytes())
                self.assertEqual(fault['observed']['container'],'exact-created-container')
                self.assertEqual(runtime.worker('task',2),'sent')
            attempts=json.loads((root/'compose-attempts/deployment-key.json').read_bytes())
            self.assertEqual(attempts['calls'],2)  # The integrated proof must reject this.
            self.assertEqual(json.loads((root/'compose-ack-lost.json').read_bytes())['run'],1)

    def test_production_cannot_enable_injection(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'compose-ack-loss-enabled.json').write_text('{}')
            runtime=object.__new__(FixtureRuntime)
            runtime.root=root;runtime.project=NS(qualification=False)
            with patch.object(Runtime,'worker') as worker:
                with self.assertRaisesRegex(ValueError,'qualification'):runtime.worker('task',1)
                worker.assert_not_called()
