from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch


class ProbeExitTests(unittest.TestCase):
    def test_failed_http_probe_is_saved_but_returns_failure_to_the_launcher(self):
        import probe_read_stream_recovery as p
        for status,code in [('failed',1),('passed',0)]:
            result={'status':status,'execution_id':'fixture'}
            with patch.object(p,'PROJECT','delivery-kit-port2'),patch.object(p,'PRIVATE',Path('/unused')),\
                    patch.object(p.subprocess,'check_output',return_value='sha256:'+'a'*64),\
                    patch.object(p.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=json.dumps(result))),\
                    patch.object(p,'save_receipt') as save,redirect_stdout(StringIO()):
                self.assertEqual(p.main(),code);self.assertEqual(save.call_count,2)

    def test_failed_acp_probe_is_not_a_successful_shell_qualification(self):
        import probe_acp_artifact as p
        for status,code in [('failed',1),('passed',0)]:
            result={'status':status,'execution_id':'fixture'}
            with patch('sys.argv',['probe','--decomposition','--unterminated','--allocation']),\
                    patch.object(p,'PROJECT','delivery-kit-port2'),patch.object(p,'PRIVATE',Path('/unused')),\
                    patch.object(p,'read_model_budget',return_value={'remaining':74}),\
                    patch.object(p.subprocess,'check_output',return_value='sha256:'+'a'*64),\
                    patch.object(p.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=json.dumps(result))),\
                    patch.object(p,'save_receipt') as save,redirect_stdout(StringIO()):
                self.assertEqual(p.main(),code);self.assertEqual(save.call_count,2)

    def test_deterministic_probe_saves_inspection_failure_without_promoting_partial_proof(self):
        import probe_acp_artifact as p
        for failed,expected in [(True,1),(False,0)]:
            result={'status':'passed','execution_id':'fixture','schema':'acp-decomposition-probe-v4'}
            inspection=SimpleNamespace(returncode=1 if failed else 0,stdout=json.dumps({
                'controller_read_requests':3,'provenance':'controller_request_not_read_evidence'}))
            with patch('sys.argv',['probe','--decomposition','--unterminated','--allocation','--deterministic']),\
                    patch.object(p,'PROJECT','delivery-kit-port2'),patch.object(p,'PRIVATE',Path('/unused')),\
                    patch.object(p,'read_model_budget',side_effect=[{'remaining':74,'calls':10},{'remaining':74,'calls':10},{'remaining':73,'calls':11}]),\
                    patch.object(p.subprocess,'check_output',return_value='sha256:'+'a'*64),\
                    patch.object(p.subprocess,'run',side_effect=[SimpleNamespace(returncode=0,stdout=json.dumps(result)),inspection]) as run,\
                    patch.object(p,'save_receipt') as save,redirect_stdout(StringIO()):
                self.assertEqual(p.main(),expected)
                saved=save.call_args.args[1]
                self.assertEqual(saved['decision_model_calls'],1)
                self.assertIn('PYTHONPATH=/',run.call_args.args[0])
                self.assertEqual(saved['status'],'failed' if failed else 'passed')
                if failed:self.assertEqual(saved['failure_category'],'DeterministicDispatchInspectionUnavailable')
