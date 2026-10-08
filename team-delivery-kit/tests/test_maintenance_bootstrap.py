import unittest
from bootstrap_controller_maintenance import identity,validate_controller,helper


class BootstrapTests(unittest.TestCase):
    operation='12345678-1234-1234-1234-123456789abc'
    image='sha256:'+'a'*64

    def test_no_unrelated_targets_or_mutable_images(self):
        for namespace,image in [('toso-app',self.image),('reforma',self.image),('delivery-kit-port2','latest')]:
            with self.subTest(namespace=namespace),self.assertRaises(ValueError):
                identity(namespace,self.operation,image,self.image)

    def test_exact_controller_volume_and_project(self):
        info={'image':self.image,'labels':{'com.docker.compose.project':'delivery-kit-port2','com.docker.compose.service':'execution-broker'},
              'mounts':[{'Destination':'/broker-state','Type':'volume','Name':'delivery-kit-port2_broker_state'}]}
        self.assertEqual(validate_controller(info,'delivery-kit-port2',self.image),'delivery-kit-port2_broker_state')
        with self.assertRaises(ValueError):validate_controller(info,'delivery-kit-other',self.image)
        with self.assertRaises(ValueError):validate_controller({**info,'image':'sha256:'+'b'*64},'delivery-kit-port2',self.image)

    def test_grouped_readonly_admin_helper_has_no_socket_or_model_key(self):
        args=helper('delivery-kit-port2',self.operation,self.image,'delivery-kit-port2_broker_state',self.image)
        self.assertIn('com.docker.compose.project=delivery-kit-port2-tests',args)
        self.assertIn('--rm',args);self.assertIn('--read-only',args)
        self.assertNotIn('docker.sock',' '.join(args));self.assertNotIn('OPENROUTER_API_KEY',' '.join(args))
        with self.assertRaises(ValueError):helper('delivery-kit-port2',self.operation,self.image,'other-volume',self.image)
