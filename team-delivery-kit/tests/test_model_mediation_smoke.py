import unittest
from model_mediation_smoke import command


class MediationSmokeTests(unittest.TestCase):
    def test_synthetic_probe_is_scoped_and_cannot_grant_real_delivery_authority(self):
        cmd=command('delivery-kit-port2','sha256:'+'a'*64,'11111111-1111-4111-8111-111111111111')
        source=cmd[-1];compile(source,'synthetic-probe','exec')
        self.assertIn('synthetic_mediation_transport_only',source)
        self.assertIn('"actual_artifact_read":False',source)
        self.assertIn('"delivery_approval":False',source)
        self.assertIn('"worker_tool_executed":False',source)
        self.assertIn('request_review_reconsideration',source)
        self.assertNotIn('/var/run/docker.sock',str(cmd));self.assertNotIn('/secret',str(cmd))
        self.assertIn('--rm',cmd);self.assertIn('--read-only',cmd)
        self.assertNotIn('__EXECUTION__',source)
        scope={};exec(source.split('request=')[0],scope)
        from mediation_transport_fixture import body
        self.assertEqual(scope['body']['messages'],body()['messages'])
        for invalid in ('../invalid','11111111111141118111111111111111'):
            with self.assertRaises(ValueError):command('delivery-kit-port2','sha256:'+'a'*64,invalid)
