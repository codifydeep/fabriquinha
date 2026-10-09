import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from test_portable_contract import contract


SPEC = importlib.util.spec_from_file_location(
    'workspace_lockdown_test', Path(__file__).parents[1] / 'broker/workspace_lockdown.py')
lock = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(lock)


class WorkspaceLockdownTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.base, self.work = root / 'base', root / 'work'
        self.base.mkdir()
        self.work.mkdir()
        specification = contract()
        payload = json.dumps(specification).encode()
        (self.base / 'contract.json').write_bytes(payload)
        hashes = {'contract.json': hashlib.sha256(payload).hexdigest()}
        for name, content in {'AGENTS.md': 'policy\n', 'app.py': 'x = 1\n',
                              'tests/test_old.py': 'def test_old(): pass\n'}.items():
            for folder in (self.base, self.work):
                target = folder / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content)
            hashes[name] = hashlib.sha256(content.encode()).hexdigest()
        manifest = json.dumps({'base_sha': 'a' * 40, 'files': hashes}).encode()
        (self.base / 'manifest.json').write_bytes(manifest)
        (self.work / '.delivery-kit-base.json').write_text(json.dumps({
            'base_sha': 'a' * 40,
            'manifest_sha256': hashlib.sha256(manifest).hexdigest()}))
        self.addCleanup(lambda: (self.work.chmod(0o755),
                                 (self.work / 'tests').chmod(0o755)))

    def test_tests_only_then_implementation_freezes_test(self):
        with patch.object(lock.os, 'chown'):
            lock.lockdown(self.base, self.work, ['tests/test_new.py'])
            self.assertEqual((self.work / 'tests/test_new.py').stat().st_mode & 0o777, 0o666)
            self.assertEqual((self.work / 'app.py').stat().st_mode & 0o777, 0o444)
            self.assertEqual((self.work / 'tests').stat().st_mode & 0o777, 0o555)
            (self.work / 'tests/test_new.py').write_text('def test_new(): assert False\n')
            lock.lockdown(self.base, self.work, ['app.py'])
            self.assertEqual((self.work / 'tests/test_new.py').stat().st_mode & 0o777, 0o444)
            self.assertEqual((self.work / 'app.py').stat().st_mode & 0o777, 0o666)

    def test_rejects_undeclared_file_and_scope(self):
        (self.work / 'tests/rogue.py').write_text('pass\n')
        with patch.object(lock.os, 'chown'), self.assertRaisesRegex(ValueError, 'undeclared'):
            lock.lockdown(self.base, self.work, ['tests/test_new.py'])
        (self.work / 'tests/rogue.py').unlink()
        with patch.object(lock.os, 'chown'), self.assertRaisesRegex(ValueError, 'scope'):
            lock.lockdown(self.base, self.work, ['tests/test_old.py'])

    def test_large_product_allowed_but_new_tests_keep_small_limit(self):
        (self.work / 'app.py').write_bytes(b'#' + b'x' * 40000)
        with patch.object(lock.os, 'chown'):
            lock.lockdown(self.base, self.work, ['app.py'])
            self.assertEqual((self.work / 'app.py').stat().st_mode & 0o777, 0o666)
            self.work.chmod(0o755)
            (self.work / 'tests').chmod(0o755)
            (self.work / 'tests/test_new.py').write_bytes(b'#' + b'x' * 40000)
            with self.assertRaisesRegex(ValueError, 'unsafe workspace'):
                lock.lockdown(self.base, self.work, ['tests/test_new.py'])
            (self.work / 'app.py').write_bytes(b'x' * (lock.MAX_FILE_BYTES + 1))
            with self.assertRaisesRegex(ValueError, 'unsafe workspace'):
                lock.lockdown(self.base, self.work, ['app.py'])

    def test_oversized_repair_is_hash_bound_and_never_grants_baseline_write(self):
        name='tests/test_new.py';payload=b'#'+b'x'*38509
        target=self.work/name;target.write_bytes(payload)
        repair={name:{'bytes':len(payload),'sha256':hashlib.sha256(payload).hexdigest()}}
        with patch.object(lock.os,'chown'):
            with self.assertRaisesRegex(ValueError,'unsafe workspace'):
                lock.lockdown(self.base,self.work,[name])
            wrong={name:{**repair[name],'sha256':'0'*64}}
            with self.assertRaisesRegex(ValueError,'hash drift'):
                lock.lockdown(self.base,self.work,[name],wrong)
            with self.assertRaisesRegex(ValueError,'invalid historical'):
                lock.lockdown(self.base,self.work,['app.py'],{'app.py':repair[name]})
            lock.lockdown(self.base,self.work,[name],repair)
            self.assertEqual(target.stat().st_mode & 0o777,0o666)
            self.assertEqual((self.work/'app.py').stat().st_mode & 0o777,0o444)
            target.write_text('def test_new(): assert False\n')
            lock.lockdown(self.base,self.work,[name],repair)


if __name__ == '__main__':
    unittest.main()
