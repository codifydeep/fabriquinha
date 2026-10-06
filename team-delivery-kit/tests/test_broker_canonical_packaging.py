"""A fresh image must not depend on a developer's accumulated overlay images."""
from pathlib import Path
import shlex
import unittest

ROOT=Path(__file__).resolve().parents[1]


def copies(path):
    return {tuple(shlex.split(line)[1:]) for line in path.read_text().splitlines()
            if line.startswith('COPY ') and len(shlex.split(line))==3}


class BrokerCanonicalPackagingTests(unittest.TestCase):
    def test_all_proxy_overlay_dependencies_are_in_the_fresh_build(self):
        required=set()
        for path in ROOT.glob('Dockerfile*proxy*'):
            required|={entry for entry in copies(path) if entry[0].endswith('.py')}
        self.assertEqual(required-copies(ROOT/'Dockerfile.model-proxy'),set())
    def test_all_overlay_python_dependencies_are_in_the_fresh_build(self):
        required=set()
        for path in ROOT.glob('Dockerfile.broker-read-*'):
            required|={entry for entry in copies(path) if entry[0].endswith('.py')}
        self.assertEqual(required-copies(ROOT/'Dockerfile.broker'),set())

    def test_registered_context_and_checkpoint_entrypoints_are_copied(self):
        entries=copies(ROOT/'Dockerfile.broker')
        for source,destination in (
                ('execution_context.py','/execution_context.py'),
                ('generated_context.py','/generated_context.py'),
                ('broker/failed_test_checkpoint.py','/failed_test_checkpoint.py'),
                ('broker/failed_test_checkpoint_copy.py','/failed_test_checkpoint_copy.py'),
                ('broker/pre_red_snapshot_diagnostic.py','/pre_red_snapshot_diagnostic.py')):
            self.assertIn((source,destination),entries)
