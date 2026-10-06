import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import subprocess
import unittest

from broker.pre_red_snapshot_diagnostic import inspect
from test_portable_contract import contract


class PreRedSnapshotDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name) / 'base'
        self.snapshot = Path(self.tmp.name) / 'snapshot'
        self.base.mkdir(); self.snapshot.mkdir()
        files = {'AGENTS.md': b'contract', 'app.py': b'answer = 0\n',
                 'tests/test_old.py': b'import unittest\n',
                 'tests/test_new.py': b'import unittest\nclass New(unittest.TestCase):\n def test_new(self): self.assertEqual(0, 1)\n'}
        for name, data in files.items():
            p = self.snapshot / name
            p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(data)
            if name != 'tests/test_new.py':
                p = self.base / name
                p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(data)
        (self.base / 'contract.json').write_text(json.dumps(contract()))
        hashes = {str(p.relative_to(self.base)): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in self.base.rglob('*') if p.is_file()}
        (self.base / 'manifest.json').write_text(json.dumps({'base_sha': 'a'*40, 'files': hashes}))
        self.manifest()

    def manifest(self):
        files = {str(p.relative_to(self.snapshot)): dict(bytes=p.stat().st_size,
                 sha256=hashlib.sha256(p.read_bytes()).hexdigest())
                 for p in self.snapshot.rglob('*') if p.is_file() and p.name != 'manifest.json'}
        (self.snapshot / 'manifest.json').write_text(json.dumps(dict(files=files)))

    def test_candidate_is_not_acceptance_and_output_is_not_exported(self):
        def run(argv, **kwargs):
            self.assertEqual(argv, contract()['test_command'])
            self.assertEqual(kwargs['cwd'], self.snapshot)
            return SimpleNamespace(returncode=1, stdout='', stderr=
                'FAIL: test_new (test_new.New)\nAssertionError: secret\nRan 2 tests in 0.1s\n\nFAILED (failures=1)\n')
        receipt = inspect(self.snapshot, self.base, run=run)
        self.assertTrue(receipt['red_candidate'])
        self.assertFalse(receipt['red_captured'])
        self.assertFalse(receipt['delivery_approved'])
        self.assertFalse(receipt['native_task_completed'])
        self.assertNotIn('secret', json.dumps(receipt))
        self.assertEqual(receipt['tests_executed'], 2)

    def test_changed_baseline_rejected_even_with_valid_snapshot_hash(self):
        (self.snapshot / 'app.py').write_text('answer = 1\n')
        self.manifest()
        with self.assertRaisesRegex(ValueError, 'base file changed'):
            inspect(self.snapshot, self.base, run=lambda *a, **k: self.fail('must not run'))

    def test_hash_drift_rejected(self):
        (self.snapshot / 'tests/test_new.py').write_text('changed')
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            inspect(self.snapshot, self.base)

    def test_extra_file_rejected(self):
        (self.snapshot / 'extra').write_text('extra')
        with self.assertRaisesRegex(ValueError, 'file set mismatch'):
            inspect(self.snapshot, self.base)

    def test_runner_failure_cannot_be_red_candidate(self):
        r = inspect(self.snapshot, self.base, run=lambda *a, **k:
            SimpleNamespace(returncode=2, stdout='', stderr='SyntaxError: secret\n'))
        self.assertFalse(r['red_candidate'])
        self.assertEqual(r['failure_category'], 'runner_failure_unclassified')
        self.assertNotIn('secret', json.dumps(r))

    def test_passing_tests_do_not_complete_failed_task(self):
        r = inspect(self.snapshot, self.base, run=lambda *a, **k:
            SimpleNamespace(returncode=0, stdout='OK\n', stderr=''))
        self.assertFalse(r['red_candidate'])
        self.assertFalse(r['native_task_completed'])

    def test_symlink_rejected_before_runner(self):
        target = self.snapshot / 'tests/test_new.py'
        target.unlink(); target.symlink_to(self.base / 'app.py')
        with self.assertRaisesRegex(ValueError, 'symlink forbidden'):
            inspect(self.snapshot, self.base)

    def test_timeout_does_not_become_a_red_candidate(self):
        def run(*args, **kwargs):
            self.assertEqual(kwargs['timeout'], 60)
            raise subprocess.TimeoutExpired(args[0], 60)
        with self.assertRaises(subprocess.TimeoutExpired):
            inspect(self.snapshot, self.base, run=run)
