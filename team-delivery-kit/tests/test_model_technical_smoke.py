import unittest
from model_technical_smoke import command


class TechnicalSmokeTests(unittest.TestCase):
    def test_real_correlated_decision_contract_no_tools_or_credentials_execute(self):
        execution='93e73506-580a-4fb5-834c-0eced5c34692'
        cmd=command('delivery-kit-port2','sha256:'+'a'*64,execution)
        self.assertIn('--rm',cmd)
        self.assertIn('com.docker.compose.project=delivery-kit-port2-tests',cmd)
        self.assertNotIn('/var/run/docker.sock',' '.join(cmd))
        self.assertNotIn('/secret',' '.join(cmd))
        script=cmd[-1];compile(script,'<canary>','exec')
        self.assertIn('DELIVERY_TYPED_DECISION_V1',script)
        self.assertIn('DELIVERY_STRUCTURED_DECISION_V1:technical',script)
        self.assertIn(execution,script)
        self.assertIn('hashlib.sha256(raw)',script)
        self.assertIn('decision["action"]=="escalate_cto"',script)
        self.assertNotIn('subprocess',script)

    def test_identity_and_unpinned_images_rejected(self):
        for execution,image in [('not-uuid','sha256:'+'a'*64),('93e73506-580a-4fb5-834c-0eced5c34692','worker:latest')]:
            with self.assertRaises(ValueError):command('delivery-kit-port2',image,execution)
