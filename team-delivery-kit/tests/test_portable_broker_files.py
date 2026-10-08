import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from test_portable_contract import contract


def module(name):
    path = Path(__file__).parents[1] / 'broker' / (name + '.py')
    spec = importlib.util.spec_from_file_location(name + '_portable_test', path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


base_copy = module('base_copy')
seed = module('seed_workspace')
freeze = module('snapshot_copy')
validate_snapshot = module('portable_snapshot_validate')


class PortableBrokerFilesTests(unittest.TestCase):
    def test_optional_new_code_and_snapshot_resume_preserve_required_tests(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base, work, snapshot = (root / name for name in ('base', 'work', 'snapshot'))
            for folder in (base, work, snapshot):
                folder.mkdir()
            spec = contract()
            spec.update(schema_version=2, required_files=list(spec['files']))
            spec['files'].append('optional.py')
            spec['editable_files'].append('optional.py')
            contract_bytes = json.dumps(spec).encode()
            (base / 'contract.json').write_bytes(contract_bytes)
            baseline = {'AGENTS.md': 'policy', 'app.py': 'x = 1', 'tests/test_old.py': 'def test_old(): pass'}
            hashes = {'contract.json': hashlib.sha256(contract_bytes).hexdigest()}
            for name, content in baseline.items():
                for folder in (base, work):
                    (folder / name).parent.mkdir(parents=True, exist_ok=True)
                    (folder / name).write_text(content)
                hashes[name] = hashlib.sha256(content.encode()).hexdigest()
            (base / 'manifest.json').write_text(json.dumps({'base_sha': 'a'*40, 'files': hashes}))
            (work / 'app.py').write_text('x = 2')
            (work / 'tests/test_new.py').write_text('def test_new(): pass')
            with patch.object(freeze, 'BASE', base), patch.object(freeze, 'SOURCE', work), \
                    patch.object(freeze, 'DESTINATION', snapshot):
                freeze.main()
                manifest = (snapshot / 'manifest.json').read_bytes()
                with patch.dict(os.environ, {'SNAPSHOT_RESUME': '1'}):
                    freeze.main()
                    self.assertEqual((snapshot / 'manifest.json').read_bytes(), manifest)
                    (work / 'app.py').write_text('x = 3')
                    with self.assertRaisesRegex(ValueError, 'differs'):
                        freeze.main()
            self.assertFalse((snapshot / 'optional.py').exists())
            with patch.object(validate_snapshot, 'BASE', base), patch.object(validate_snapshot, 'DELIVERY', snapshot):
                self.assertTrue(validate_snapshot.verify()['baseline_tests_intact'])

    def test_snapshot_copy_reports_required_missing_editable_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base, work, snapshot = (root / name for name in ('base', 'work', 'snapshot'))
            for folder in (base, work, snapshot):
                folder.mkdir()
            (base / 'contract.json').write_text(json.dumps(contract()))
            (base / 'manifest.json').write_text(json.dumps({'files': {}}))
            output = io.StringIO()
            with patch.object(freeze, 'BASE', base), patch.object(freeze, 'SOURCE', work), \
                    patch.object(freeze, 'DESTINATION', snapshot), redirect_stdout(output):
                with self.assertRaisesRegex(ValueError, 'required artifact missing'):
                    freeze.main()
            reported = json.loads(output.getvalue())
            self.assertEqual(reported['error'], 'required_artifact_missing')
            self.assertIn('app.py', reported['missing'])

    def test_base_seed_and_snapshot_use_operator_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, base, work, snapshot = (root / name for name in ('source', 'base', 'work', 'snapshot'))
            for folder in (source, base, work, snapshot):
                folder.mkdir()
            spec = contract()
            (source / 'tests').mkdir()
            (source / 'AGENTS.md').write_text('policy\n')
            (source / 'app.py').write_text('def value(): return 1\n')
            (source / 'tests/test_old.py').write_text('def test_old(): assert True\n')
            (source / 'contract.json').write_text(json.dumps(spec))
            names = ('AGENTS.md', 'app.py', 'tests/test_old.py', 'contract.json')
            payload = {'base_sha': 'a' * 40, 'files': {
                name: hashlib.sha256((source / name).read_bytes()).hexdigest() for name in names}}
            (source / 'manifest.json').write_text(json.dumps(payload))
            with patch.object(base_copy, 'SOURCE', source), patch.object(base_copy, 'TARGET', base):
                base_copy.main()
            with patch.object(seed, 'BASE', base), patch.object(seed, 'WORK', work), \
                    patch.dict(os.environ, {'BASE_MANIFEST_SHA256': hashlib.sha256(
                        (source / 'manifest.json').read_bytes()).hexdigest()}):
                seed.main()
            self.assertFalse((work / 'contract.json').exists())
            self.assertEqual((work / 'tests/test_old.py').read_text(), 'def test_old(): assert True\n')
            (work / 'app.py').write_text('def value(): return 2\n')
            (work / 'tests/test_new.py').write_text('def test_new(): assert True\n')
            with patch.object(freeze, 'BASE', base), patch.object(freeze, 'SOURCE', work), \
                    patch.object(freeze, 'DESTINATION', snapshot):
                freeze.main()
            manifest = json.loads((snapshot / 'manifest.json').read_text())
            self.assertEqual(set(manifest['files']), set(spec['files']))
            self.assertFalse((snapshot / 'contract.json').exists())
            with patch.object(validate_snapshot, 'BASE', base), \
                    patch.object(validate_snapshot, 'DELIVERY', snapshot), \
                    patch.dict(os.environ, {'REQUIRED_TESTS': 'test_new'}):
                result = validate_snapshot.verify()
            self.assertEqual(result['mode'], 'portable')
            self.assertTrue(result['baseline_tests_intact'])
            self.assertEqual(result['diagnostic_file_sha256'],
                {'app.py': hashlib.sha256((snapshot / 'app.py').read_bytes()).hexdigest()})
            self.assertNotIn('tests/test_old.py', result['diagnostic_file_sha256'])
            self.assertNotIn('tests/test_new.py', result['diagnostic_file_sha256'])
            if os.environ.get('RUN_PORTABLE_DOCKER_TEST') == '1':
                run = subprocess.run([
                    'docker', 'run', '--rm', '--network', 'none', '--read-only',
                    '--user', '10000:10000', '--cap-drop', 'ALL',
                    '--security-opt', 'no-new-privileges',
                    '--mount', f'type=bind,source={base},target=/base,readonly',
                    '--mount', f'type=bind,source={snapshot},target=/delivery,readonly',
                    '--env', 'REQUIRED_TESTS=test_new', '--entrypoint', 'python',
                    'delivery-kit-eval-broker:20260928.18', '/snapshot_validate.py'],
                    capture_output=True, text=True, check=True)
                self.assertEqual(json.loads(run.stdout)['mode'], 'portable')
            (snapshot / 'tests/test_old.py').chmod(0o600)
            (snapshot / 'tests/test_old.py').write_text('def test_old(): pass\n')
            with patch.object(validate_snapshot, 'BASE', base), \
                    patch.object(validate_snapshot, 'DELIVERY', snapshot):
                with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                    validate_snapshot.verify()


if __name__ == '__main__':
    unittest.main()
