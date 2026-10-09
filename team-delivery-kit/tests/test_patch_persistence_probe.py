import unittest
from probe_patch_persistence import classify
from run_patch_persistence_probe import command


class PatchPersistenceTests(unittest.TestCase):
    def receipt(self,**extra):
        return dict(operation='patch_handler_receipt_v1',delivery_approval=False,
                    author_retry_authorized=False,**extra)

    def test_hashes_distinguish_persistent_noop_and_later_change(self):
        changed=self.receipt(changed=True,no_change=False)
        self.assertEqual(classify('a','b','b',changed),'observed_persistent_change')
        self.assertEqual(classify('a','b','a',changed),'observed_later_change')
        self.assertEqual(classify('a','a','a',self.receipt(changed=False,no_change=True)),'observed_noop')

    def test_success_without_hash_change_is_inconclusive(self):
        self.assertEqual(classify('a','a','a',self.receipt(changed=True)),'inconclusive')

    def test_success_without_diff_and_without_write_is_observed_not_inferred(self):
        self.assertEqual(classify('a','a','a',self.receipt(success=True,changed=False,diff_bytes=0)),
                         'observed_unchanged_success')

    def test_noop_claim_with_later_change_is_inconclusive(self):
        self.assertEqual(classify('a','a','b',self.receipt(no_change=True)),'inconclusive')

    def test_approval_or_unknown_handler_receipt_rejected(self):
        for value in ({},dict(self.receipt(),delivery_approval=True)):
            with self.assertRaises(ValueError):classify('a','b','b',value)

    def test_launcher_has_only_synthetic_mount_and_no_network_or_socket(self):
        cmd=command('sha256:'+'a'*64)
        self.assertEqual(cmd[cmd.index('--network')+1],'none')
        self.assertEqual(cmd[cmd.index('--user')+1],'10000:10000')
        self.assertEqual(cmd.count('-v'),1)
        self.assertTrue(cmd[cmd.index('-v')+1].endswith(':/probe_patch_persistence.py:ro'))
        self.assertIn('HERMES_WRITE_SAFE_ROOT=/tmp',cmd)
        self.assertIn('com.docker.compose.project=delivery-kit-port2-tests',cmd)
        self.assertFalse(any('docker.sock' in v or 'TOKEN=' in v for v in cmd))
        with self.assertRaises(ValueError):command('latest')

    def test_observed_fixture_bootstraps_root_owner_then_drops_to_worker(self):
        cmd=command('sha256:'+'a'*64,True)
        self.assertIn('HERMES_FENCED_INPLACE_WRITES=1',cmd)
        self.assertIn('DELIVERY_PROBE_REQUIRE_OBSERVATION=1',cmd)
        self.assertEqual(cmd[cmd.index('--cap-drop')+1],'ALL')
        self.assertEqual(cmd.count('-v'),1)
