import unittest
from model_strict_tool_smoke import command


class StrictToolSmokeTests(unittest.TestCase):
    def test_probe_is_grouped_metered_and_never_executes_proposed_tools(self):
        cmd=command('delivery-kit-port2','sha256:'+'a'*64)
        self.assertIn('--rm',cmd)
        self.assertIn('com.docker.compose.project=delivery-kit-port2-tests',cmd)
        self.assertIn('delivery-kit-port2_model',cmd)
        self.assertNotIn('/var/run/docker.sock',' '.join(cmd))
        self.assertNotIn('/secret',' '.join(cmd))
        script=cmd[-1]
        compile(script,'<probe>','exec')
        self.assertIn('for strict in (True,False)',script)
        self.assertIn('"require_parameters":True',script)
        self.assertIn('http://model-proxy:8080/api/v1/chat/completions',script)
        self.assertNotIn('subprocess',script)
        self.assertIn('"tool_executed":False',script)
        self.assertIn('qualification_source_proposal',script)
        self.assertNotIn('"submit_test_source"',script)

    def test_unbounded_or_unpinned_targets_are_rejected(self):
        for namespace,image in [('other','sha256:'+'a'*64),('delivery-kit-port2','worker:latest')]:
            with self.assertRaises(ValueError):command(namespace,image)
