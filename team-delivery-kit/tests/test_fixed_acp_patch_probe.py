import inspect
import unittest
from probe_acp_fixed_patch import fixture_server,offline_bootstrap,remote_probe,valid_inspection


class FixedAcpPatchProbeTests(unittest.TestCase):
    def test_all_native_events_and_inspection_invariants_required(self):
        receipts=dict(actual_patch_calls=2,actual_read_calls=2,paired_patch_results=1,
            tool_protocol_valid=True,syntax_rejected_patch_calls=1)
        record=dict(requests=5,uid=10000,writer_sha256='a'*64,rejected_patch_preserved_bytes=True,
            exact_quotes_preserved=True,baseline_unchanged=True,credentials_absent=True)
        self.assertTrue(valid_inspection(receipts,record,'a'*64))
        for key in record:
            self.assertFalse(valid_inspection(receipts,dict(record,**{key:False}),'a'*64))
        for key in receipts:
            self.assertFalse(valid_inspection(dict(receipts,**{key:False}),record,'a'*64))
        self.assertFalse(valid_inspection(receipts,record,'b'*64))

    def test_fixed_programs_compile_and_are_offline_only(self):
        for function in (fixture_server,offline_bootstrap,remote_probe,valid_inspection):
            compile(inspect.getsource(function),'fixed-acp-fixture','exec')
        server=inspect.getsource(fixture_server)
        self.assertIn("('127.0.0.1',18088)",server);self.assertIn('if step>5:',server)
        remote=inspect.getsource(remote_probe)
        self.assertIn("NetworkMode='none'",remote);self.assertIn('Transport(offline_docker',remote)
        self.assertIn('model_calls=0,model_authorship=False',remote)
        self.assertIn("payload.get('Cmd')==['python','/worker_model_config.py']",remote)
        self.assertIn("payload.get('User')!='10000:10000'",remote)
        self.assertIn('PYTHONPATH=/:/opt/hermes',remote)
        self.assertNotIn('force=true',remote)
