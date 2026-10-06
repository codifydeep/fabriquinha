"""Discardable controller-runner qualification, not product acceptance."""
from pathlib import Path
import unittest


class IsolationTests(unittest.TestCase):
    def test_full_suite_executes(self):
        self.assertEqual(2 + 2, 4)

    def test_delivery_cannot_be_modified(self):
        with self.assertRaises(OSError):
            Path('/delivery/test_isolation.py').write_text('modified')

    def test_no_infrastructure_credentials_or_socket(self):
        self.assertFalse(Path('/secret').exists())
        self.assertFalse(Path('/var/run/docker.sock').exists())
