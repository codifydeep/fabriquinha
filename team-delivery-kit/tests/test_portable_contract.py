import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from portable_contract import is_test_path, validate
from portable_preflight import verify
from portable_qualification import run_frozen_tests, verify_http_qa
from unittest.mock import patch
from io import BytesIO
from urllib.error import HTTPError


def contract():
    return {
        'schema_version': 1, 'repository': 'codifydeep/descartavel2',
        'base_branch': 'main',
        'files': ['AGENTS.md', 'app.py', 'tests/test_old.py', 'tests/test_new.py'],
        'protected_files': ['AGENTS.md', 'tests/test_old.py'],
        'editable_files': ['app.py', 'tests/test_new.py'],
        'test_files': ['tests/test_old.py', 'tests/test_new.py'],
        'test_roots': ['tests'],
        'test_command': ['python3', '-m', 'unittest', 'discover', '-s', 'tests', '-q'],
        'test_image': 'python@sha256:' + 'a' * 64,
        'test_success_pattern': r'Ran [1-9][0-9]* tests? in [^\n]+\n\nOK',
        'test_count_pattern': r'Ran ([0-9]+) tests? in ',
        'qa_cases': [{'path': '/health', 'status': 200,
                      'expected_json': {'status': 'ok'}}],
    }


class PortableContractTests(unittest.TestCase):
    def test_business_json_can_omit_sha_when_health_binds_it(self):
        spec = contract()
        spec['schema_version'] = 2
        spec['required_files'] = list(spec['files'])
        spec['qa_cases'].append({'path': '/summary', 'status': 200,
                                 'expected_json': {'total': 0}, 'bind_source_sha': False})
        class Response(BytesIO):
            status = 200
        class Opener:
            def open(self, url, **kwargs):
                payload = {'status': 'ok', 'source_sha': 'a' * 40} if url.endswith('/health') else {'total': 0}
                return Response(json.dumps(payload).encode())
        with patch('portable_qualification.urllib.request.build_opener', return_value=Opener()):
            self.assertEqual(verify_http_qa('http://127.0.0.1:19422', 'a' * 40, spec)['cases'], 2)
        spec['qa_cases'] = spec['qa_cases'][1:]
        with self.assertRaisesRegex(ValueError, 'source-bound health'):
            validate(spec)

    def test_schema_two_html_qa_checks_type_and_content(self):
        spec = contract()
        spec['schema_version'] = 2
        spec['required_files'] = list(spec['files'])
        spec['qa_cases'] = [{'path': '/', 'status': 200, 'content_type': 'text/html',
                             'text_contains': ['<html', '<form'] }]
        validate(spec)

        class Response(BytesIO):
            status = 200
            headers = {'Content-Type': 'text/html; charset=utf-8'}

        class Opener:
            def open(self, *_args, **_kwargs):
                return Response(b'<html><form></form></html>')

        with patch('portable_qualification.urllib.request.build_opener', return_value=Opener()):
            self.assertEqual(verify_http_qa('http://127.0.0.1:19422', 'a' * 40, spec)['cases'], 1)
        spec['qa_cases'][0]['text_contains'] = ['missing']
        with patch('portable_qualification.urllib.request.build_opener', return_value=Opener()):
            with self.assertRaisesRegex(ValueError, 'content mismatch'):
                verify_http_qa('http://127.0.0.1:19422', 'a' * 40, spec)

        class Missing:
            def open(self, *_args, **_kwargs):
                raise HTTPError('http://127.0.0.1:19422/', 404, 'not found', {}, None)

        with patch('portable_qualification.urllib.request.build_opener', return_value=Missing()):
            with self.assertRaisesRegex(ValueError, 'post-deploy status mismatch: /'):
                verify_http_qa('http://127.0.0.1:19422', 'a' * 40, spec)

    def test_full_python_discovery_covers_nested_baseline_tests(self):
        self.assertTrue(is_test_path('test_calc.py', '.', 'python3'))
        self.assertTrue(is_test_path('slug_tests/test_german.py', '.', 'python3'))
        self.assertTrue(is_test_path('tests/test_bootstrap_health.py', '.', 'python3'))
        self.assertFalse(is_test_path('tests/__init__.py', '.', 'python3'))

    def test_root_level_python_tests_are_protected(self):
        spec = contract()
        spec.update(files=['AGENTS.md', 'app.py', 'test_old.py', 'test_new.py'],
                    protected_files=['AGENTS.md', 'test_old.py'],
                    editable_files=['app.py', 'test_new.py'],
                    test_files=['test_old.py', 'test_new.py'],
                    test_roots=['.'],
                    test_command=['python3', '-m', 'unittest', 'discover', '-s', '.', '-q'])
        self.assertEqual(validate(spec)['test_roots'], ['.'])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, snapshot = root / 'repo', root / 'snapshot'
            repo.mkdir()
            snapshot.mkdir()
            subprocess.run(['git', '-C', str(repo), 'init', '-q', '-b', 'main'], check=True)
            subprocess.run(['git', '-C', str(repo), 'remote', 'add', 'origin',
                            'https://github.com/codifydeep/descartavel2.git'], check=True)
            for name, content in {'AGENTS.md': 'policy\n', 'app.py': 'x = 1\n',
                                  'test_old.py': 'def test_old(): pass\n',
                                  'test_hidden.py': 'def test_hidden(): pass\n'}.items():
                (repo / name).write_text(content)
            subprocess.run(['git', '-C', str(repo), 'add', '.'], check=True)
            subprocess.run(['git', '-C', str(repo), '-c', 'user.name=Test',
                            '-c', 'user.email=test@example.org', 'commit', '-qm', 'base'], check=True)
            sha = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip()
            for name in spec['files']:
                (snapshot / name).write_text((repo / name).read_text() if (repo / name).exists()
                                              else 'def test_new(): pass\n')
            (snapshot / 'manifest.json').write_text(json.dumps({'files': {
                name: {'sha256': hashlib.sha256((snapshot / name).read_bytes()).hexdigest(),
                       'bytes': (snapshot / name).stat().st_size} for name in spec['files']}}))
            with self.assertRaisesRegex(ValueError, 'test tree is not fully protected'):
                verify(repo, sha, snapshot, spec)

    @unittest.skipUnless(os.environ.get('RUN_PORTABLE_DOCKER_TEST') == '1',
                         'Docker smoke runs explicitly')
    def test_offline_node_frozen_test_runner(self):
        specification = contract()
        specification.update(
            files=['AGENTS.md', 'Dockerfile', 'math.js', 'tests/test_old.test.js',
                   'tests/test_new.test.js'],
            protected_files=['AGENTS.md', 'Dockerfile', 'tests/test_old.test.js'],
            editable_files=['math.js', 'tests/test_new.test.js'],
            test_files=['tests/test_old.test.js', 'tests/test_new.test.js'],
            test_command=['node', '--test'],
            test_image='node@sha256:b6f26b36c8ff49624cfdac716b8ea1138d606df02586a77d364bb5536a634f85',
            test_success_pattern=r'(?m)^# pass 2$',
            test_count_pattern=r'(?m)^# tests ([0-9]+)$')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'tests').mkdir()
            (root / 'AGENTS.md').write_text('Preserve tests.\n')
            (root / 'Dockerfile').write_text('FROM scratch\n')
            (root / 'math.js').write_text('exports.add = (a, b) => a + b;\n')
            for name, left, right, expected in (
                ('test_old.test.js', 1, 2, 3), ('test_new.test.js', 2, 3, 5)):
                (root / 'tests' / name).write_text(
                    "const test = require('node:test');\n"
                    "const assert = require('node:assert/strict');\n"
                    "const { add } = require('../math');\n"
                    f"test('addition', () => assert.equal(add({left}, {right}), {expected}));\n")
            self.assertEqual(run_frozen_tests(root, specification)['tests'], 2)

    def test_rejects_unsafe_contracts(self):
        bad = contract()
        bad['files'][0] = '../secret'
        with self.assertRaises(ValueError):
            validate(bad)
        bad = contract()
        bad['test_image'] = 'python:latest'
        with self.assertRaises(ValueError):
            validate(bad)
        bad = contract()
        bad['test_command'] = 'python -m unittest'
        with self.assertRaises(ValueError):
            validate(bad)

    def test_frozen_delivery_preserves_old_tests(self):
        spec = validate(contract())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, snapshot = root / 'repo', root / 'snapshot'
            repo.mkdir()
            snapshot.mkdir()
            subprocess.run(['git', '-C', str(repo), 'init', '-q', '-b', 'main'], check=True)
            subprocess.run(['git', '-C', str(repo), 'remote', 'add', 'origin',
                            'https://github.com/codifydeep/descartavel2.git'], check=True)
            (repo / 'tests').mkdir()
            (repo / 'AGENTS.md').write_text('policy\n')
            (repo / 'app.py').write_text('def value(): return 1\n')
            (repo / 'tests/test_old.py').write_text('def test_old(): assert True\n')
            subprocess.run(['git', '-C', str(repo), 'add', '.'], check=True)
            subprocess.run(['git', '-C', str(repo), '-c', 'user.name=Test',
                            '-c', 'user.email=test@example.org', 'commit', '-qm', 'base'], check=True)
            sha = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip()
            (snapshot / 'tests').mkdir()
            for name in ('AGENTS.md', 'tests/test_old.py'):
                (snapshot / name).write_bytes((repo / name).read_bytes())
            (snapshot / 'app.py').write_text('def value(): return 2\n')
            (snapshot / 'tests/test_new.py').write_text('def test_new(): assert True\n')
            def manifest():
                (snapshot / 'manifest.json').write_text(json.dumps({'files': {
                    name: {'sha256': hashlib.sha256((snapshot / name).read_bytes()).hexdigest(),
                           'bytes': (snapshot / name).stat().st_size}
                    for name in spec['files']}}))
            manifest()
            result = verify(repo, sha, snapshot, spec)
            self.assertEqual(result['new_test_files'], ['tests/test_new.py'])
            (snapshot / 'tests/test_old.py').write_text('def test_old(): pass\n')
            manifest()
            with self.assertRaisesRegex(ValueError, 'protected baseline'):
                verify(repo, sha, snapshot, spec)
            (repo / 'tests/helper.py').write_text('def helper(): return True\n')
            subprocess.run(['git', '-C', str(repo), 'add', 'tests/helper.py'], check=True)
            subprocess.run(['git', '-C', str(repo), '-c', 'user.name=Test',
                            '-c', 'user.email=test@example.org', 'commit', '-qm', 'more baseline tests'], check=True)
            newer_sha = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip()
            with self.assertRaisesRegex(ValueError, 'test tree is not fully protected'):
                verify(repo, newer_sha, snapshot, spec)

    @unittest.skipUnless(os.environ.get('RUN_PORTABLE_DOCKER_TEST') == '1',
                         'Docker smoke runs explicitly')
    def test_offline_frozen_test_runner(self):
        spec = contract()
        spec['test_image'] = ('python@sha256:'
                              '392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e')
        with tempfile.TemporaryDirectory() as directory:
            snapshot = Path(directory)
            (snapshot / 'tests').mkdir()
            (snapshot / 'app.py').write_text('def value(): return 2\n')
            (snapshot / 'tests/test_old.py').write_text(
                'import unittest\nfrom app import value\n'
                'class Old(unittest.TestCase):\n def test_old(self): self.assertEqual(value(), 2)\n')
            (snapshot / 'tests/test_new.py').write_text(
                'import unittest\nfrom app import value\n'
                'class New(unittest.TestCase):\n def test_new(self): self.assertEqual(value(), 2)\n')
            self.assertEqual(run_frozen_tests(snapshot, spec)['status'], 'passed')
            (snapshot / 'tests/test_new.py').write_text(
                'import unittest\nclass New(unittest.TestCase):\n'
                ' @unittest.skip("not ready")\n def test_new(self): pass\n')
            with self.assertRaisesRegex(ValueError, 'full-suite'):
                run_frozen_tests(snapshot, spec)


if __name__ == '__main__':
    unittest.main()
