import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from broker.base_gate import verify_base_compatible


FIXTURE = Path(__file__).parents[1] / 'tests/fixtures/tdd'
FILES = ('AGENTS.md', 'calc.py', 'test_calc.py')


class BaseGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name) / 'repo'
        self.snapshot = Path(self.temp.name) / 'snapshot'
        self.repo.mkdir(); self.snapshot.mkdir()
        for name in FILES:
            (self.repo / name).write_bytes((FIXTURE / name).read_bytes())
        self.git('init', '-q')
        self.git('config', 'user.email', 'eval@example.invalid')
        self.git('config', 'user.name', 'Eval')
        self.git('add', '.')
        self.git('commit', '-qm', 'base')
        self.base = self.git('rev-parse', 'HEAD').strip()
        for name in FILES:
            (self.snapshot / name).write_bytes((self.repo / name).read_bytes())
        (self.snapshot / 'calc.py').write_text((self.snapshot / 'calc.py').read_text() + '\n\ndef square(value):\n    return value * value\n')
        tests = (self.snapshot / 'test_calc.py').read_text().replace('from calc import add, multiply', 'from calc import add, multiply, square')
        (self.snapshot / 'test_calc.py').write_text(tests + '\n\nclass SquareTests(unittest.TestCase):\n    def test_square_positive(self):\n        self.assertEqual(square(4), 16)\n')
        self.manifest()

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.repo), *args], text=True)

    def manifest(self):
        files = {}
        for name in FILES:
            data = (self.snapshot / name).read_bytes()
            files[name] = {'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}
        (self.snapshot / 'manifest.json').write_text(json.dumps({'files': files}, sort_keys=True, separators=(',', ':')))

    def test_accepts_new_code_and_test_on_exact_base(self):
        receipt = verify_base_compatible(self.repo, self.base, self.snapshot)
        self.assertEqual(receipt['base_sha'], self.base)
        self.assertEqual(receipt['new_tests'], ['test_square_positive'])

    def test_rejects_removed_old_test_even_with_fresh_manifest(self):
        source = (self.snapshot / 'test_calc.py').read_text()
        source = source.replace('    def test_multiply_by_zero(self):\n        self.assertEqual(multiply(5, 0), 0)\n\n', '')
        (self.snapshot / 'test_calc.py').write_text(source)
        self.manifest()
        with self.assertRaisesRegex(ValueError, 'pre-existing test'):
            verify_base_compatible(self.repo, self.base, self.snapshot)

    def test_rejects_policy_change(self):
        (self.snapshot / 'AGENTS.md').write_text('different instructions')
        self.manifest()
        with self.assertRaisesRegex(ValueError, 'AGENTS'):
            verify_base_compatible(self.repo, self.base, self.snapshot)

    def test_rejects_moved_base(self):
        with self.assertRaisesRegex(ValueError, 'base moved'):
            verify_base_compatible(self.repo, '0' * 40, self.snapshot)
