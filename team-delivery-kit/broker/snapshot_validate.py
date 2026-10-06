"""Fixed offline validator for one frozen disposable Python delivery."""
import ast
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import sys

DELIVERY = Path('/delivery')
BASE_TEST = Path('/base/test_calc.py')
BASE_CODE = Path('/base/calc.py')
FILES = {'AGENTS.md', 'calc.py', 'test_calc.py'}


class RequiredTestMissing(ValueError):
    def __init__(self, names):
        self.names = names
        super().__init__('required reviewer-requested test missing')


def methods(path):
    tree = ast.parse(path.read_text())
    return {node.name: ast.dump(node, include_attributes=False)
            for parent in tree.body if isinstance(parent, ast.ClassDef)
            for node in parent.body if isinstance(node, ast.FunctionDef)}


def validate():
    if (BASE_TEST.parent / 'contract.json').exists():
        from portable_snapshot_validate import verify
        return verify()
    if {p.name for p in DELIVERY.iterdir()} != FILES | {'manifest.json'}:
        raise ValueError('snapshot file set changed')
    manifest_bytes = (DELIVERY / 'manifest.json').read_bytes()
    manifest = json.loads(manifest_bytes)
    if set(manifest) != {'files'} or set(manifest['files']) != FILES:
        raise ValueError('snapshot manifest changed')
    for name in FILES:
        path = DELIVERY / name
        if path.is_symlink() or not path.is_file():
            raise ValueError('snapshot entry is not a regular file')
        content = path.read_bytes()
        if len(content) != manifest['files'][name]['bytes'] or hashlib.sha256(content).hexdigest() != manifest['files'][name]['sha256']:
            raise ValueError('snapshot hash mismatch')
    original = methods(BASE_TEST)
    delivered = methods(DELIVERY / 'test_calc.py')
    required = [name for name in os.environ.get('REQUIRED_TESTS', '').split(',') if name]
    if any(not re.fullmatch(r'test_[A-Za-z0-9_]{1,100}', name) for name in required):
        raise ValueError('invalid required test name')
    for name in original:
        if delivered.get(name) != original.get(name):
            raise ValueError('preexisting test modified')
    missing = [name for name in required if name not in delivered]
    if missing:
        raise RequiredTestMissing(missing)
    if not set(delivered) - set(original):
        raise ValueError('new behavior lacks test')
    if (DELIVERY / 'calc.py').read_bytes() == BASE_CODE.read_bytes():
        raise ValueError('new behavior lacks implementation')
    result = subprocess.run([sys.executable, '-m', 'unittest', '-v'],
                            cwd=DELIVERY, env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'},
                            text=True, capture_output=True, timeout=10)
    count_match = re.search(r'Ran (\d+) tests? in ', result.stderr)
    count = int(count_match.group(1)) if count_match else 0
    if (result.returncode or count < len([name for name in delivered if name.startswith('test_')])
            or count < 3 or '\nOK\n' not in result.stderr
            or any(marker in result.stderr.lower() for marker in
                   ('skipped=', 'expected failure', 'unexpected success'))):
        raise ValueError('frozen full suite failed')
    return {'manifest_sha256': hashlib.sha256(manifest_bytes).hexdigest(),
            'tests': count, 'baseline_tests_intact': True}


if __name__ == '__main__':
    try:
        result = validate()
        print(json.dumps(result, sort_keys=True), flush=True)
        if result.get('error'):
            sys.exit(2)
    except RequiredTestMissing as error:
        print(json.dumps({'error': 'required_test_missing', 'missing': error.names}), flush=True)
        sys.exit(2)
    except ValueError as error:
        print(json.dumps({'error': 'validation_failed', 'category': type(error).__name__,
                          'reason': str(error)[:300]}), flush=True)
        sys.exit(1)
