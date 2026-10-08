import unittest
from controller_maintenance_cli import arguments


class MaintenanceCLITests(unittest.TestCase):
    def test_exact_controller_and_fixed_operations_only(self):
        operation = '12345678-1234-1234-1234-123456789abc'
        command = arguments('delivery-kit-port2', 'seal', operation)
        self.assertEqual(command[4], 'delivery-kit-port2-execution-broker-1')
        self.assertEqual(command[-2:], ['seal', operation])
        for namespace, action, identity in [('toso-app', 'seal', operation),
                ('delivery-kit-port2;echo', 'seal', operation), ('delivery-kit-port2', 'shell', operation),
                ('delivery-kit-port2', 'seal', 'not-a-uuid')]:
            with self.subTest(namespace=namespace, action=action), self.assertRaises(ValueError):
                arguments(namespace, action, identity)

    def test_status_does_not_require_or_create_an_operation(self):
        command = arguments('delivery-kit-port2', 'status', '')
        self.assertEqual(command[-2:], ['status', ''])
