import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import scope_runtime_inventory as inventory


class ScopeRuntimeInventoryTests(unittest.TestCase):
    def test_broker_inventory_includes_mount_resolver_and_current_public_scope_code(self):
        expected=inventory.manifest('broker')
        for name in ('/broker.py','/test_revision_review.py','/native_scope_note.py','/product_scope_execution.py','/product_scope_worker.py'):
            self.assertEqual(len(expected[name]),64)
        command=inventory.command('sha256:'+'a'*64,'broker')
        self.assertEqual(json.loads(command[-1]),expected)
        self.assertIn('--network=none',command);self.assertIn('--rm',command)
        self.assertIn('com.docker.compose.project=delivery-kit-port2-tests',command)
        self.assertFalse(any('docker.sock' in value or '/secret' in value for value in command))

    def test_proxy_inventory_is_separate_and_arbitrary_image_or_role_rejected(self):
        self.assertEqual(set(inventory.manifest('proxy')),{'/product_scope_contract.py','/decision_schema.py','/typed_decision_contract.py'})
        with self.assertRaises(ValueError):inventory.command('latest','broker')
        with self.assertRaises(ValueError):inventory.manifest('arbitrary')

    def test_inventory_failure_preserves_exit_status_without_dumping_command(self):
        with patch('sys.argv',['inventory','--image','sha256:'+'a'*64,'--role','broker']),\
                patch.object(inventory.subprocess,'run',return_value=SimpleNamespace(returncode=1)),\
                self.assertRaises(SystemExit) as error:
            inventory.main()
        self.assertEqual(error.exception.code,1)
