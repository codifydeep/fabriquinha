import unittest
from model_policy_smoke import command
from model_policy import MODEL


class ModelSmokeIsolationTests(unittest.TestCase):
    def test_metered_model_network_no_secrets_no_host_or_socket(self):
        args=command('delivery-kit-port2','sha256:'+'a'*64)
        self.assertIn('delivery-kit-port2_model',args)
        self.assertIn('--rm',args)
        self.assertIn('com.docker.compose.project=delivery-kit-port2-tests',args)
        self.assertIn(MODEL,args[-1])
        self.assertNotIn('--mount',args)
        self.assertNotIn('--env',args)
        self.assertNotIn('OPENROUTER_API_KEY',args[-1])
        self.assertIn('scope',args[-1])

    def test_mutable_images_or_arbitrary_namespace_are_rejected(self):
        for namespace,image in (('toso-local','sha256:'+'a'*64),('delivery-kit-port2','latest')):
            with self.assertRaises(ValueError):command(namespace,image)
