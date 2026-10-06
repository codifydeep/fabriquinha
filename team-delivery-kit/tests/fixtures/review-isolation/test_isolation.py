"""Trusted, model-free checks of the review runner container boundary."""
import os
from pathlib import Path
import socket
import unittest


class OfflineReviewIsolationTests(unittest.TestCase):
    def test_delivery_is_readonly_but_temporary_space_is_writable(self):
        target = Path('/delivery/test_isolation.py')
        before = target.read_bytes()
        with self.assertRaises(OSError):
            with target.open('ab') as stream:
                stream.write(b'forbidden')
        self.assertEqual(target.read_bytes(), before)
        self.assertTrue(os.access('/tmp', os.W_OK))

    def test_socket_and_credentials_are_absent(self):
        self.assertFalse(Path('/var/run/docker.sock').exists())
        self.assertFalse(Path('/broker-state').exists())
        self.assertFalse(Path('/session-state').exists())
        self.assertNotIn('DELIVERY_REVIEW_SUITE_CAPABILITY', os.environ)
        self.assertNotIn('OPENROUTER_API_KEY', os.environ)
        self.assertNotIn('GITHUB_TOKEN', os.environ)

    def test_network_is_unavailable(self):
        with socket.socket() as client:
            client.settimeout(1)
            with self.assertRaises(OSError):
                client.connect(('1.1.1.1', 443))
