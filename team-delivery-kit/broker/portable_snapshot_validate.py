"""Fixed structural validator for an operator-owned portable frozen delivery."""
import hashlib
import json
import os
from pathlib import Path
import re

from portable_contract import MAX_FILE_BYTES, validate, validate_delivery_files, is_test_path


BASE = Path('/base')
DELIVERY = Path('/delivery')


def regular_within(root, name):
    path = root / name
    parents = list(path.parents)[:len(Path(name).parts) - 1]
    if path.is_symlink() or any(parent.is_symlink() for parent in parents) or not path.is_file():
        raise ValueError('invalid frozen file: ' + name)
    content = path.read_bytes()
    if len(content) > MAX_FILE_BYTES:
        raise ValueError('frozen file too large')
    return content


def verify():
    contract_bytes = regular_within(BASE, 'contract.json')
    contract = validate(json.loads(contract_bytes))
    base_manifest = json.loads(regular_within(BASE, 'manifest.json'))
    if (set(base_manifest) != {'base_sha', 'files'} or
            not isinstance(base_manifest['files'], dict) or
            not set(base_manifest['files']) <= set(contract['files']) | {'contract.json'} or
            base_manifest['files'].get('contract.json') != hashlib.sha256(contract_bytes).hexdigest()):
        raise ValueError('base contract mismatch')
    manifest_bytes = regular_within(DELIVERY, 'manifest.json')
    manifest = json.loads(manifest_bytes)
    if set(manifest) != {'files'} or not isinstance(manifest['files'], dict):
        raise ValueError('frozen file set mismatch')
    names = validate_delivery_files(contract, manifest['files'], base_manifest['files'])
    actual = {str(path.relative_to(DELIVERY)) for path in DELIVERY.rglob('*')
              if path.is_file() or path.is_symlink()}
    if actual != set(names) | {'manifest.json'}:
        raise ValueError('unexpected frozen entry')
    changed_code, new_tests = [], []
    for name in names:
        content = regular_within(DELIVERY, name)
        if manifest['files'][name] != {
                'sha256': hashlib.sha256(content).hexdigest(), 'bytes': len(content)}:
            raise ValueError('frozen hash mismatch: ' + name + ' actual=' + hashlib.sha256(content).hexdigest())
        base_path = BASE / name
        if name in base_manifest['files']:
            original = regular_within(BASE, name)
            if hashlib.sha256(original).hexdigest() != base_manifest['files'][name]:
                raise ValueError('base hash mismatch: ' + name)
            if name in contract['protected_files'] or name in contract['test_files']:
                if content != original:
                    raise ValueError('pre-existing protected file changed: ' + name
                                     + ' expected=' + base_manifest['files'][name]
                                     + ' actual=' + hashlib.sha256(content).hexdigest())
            elif content != original:
                changed_code.append(name)
        elif name in contract['test_files']:
            if base_path.exists():
                raise ValueError('undeclared base test')
            new_tests.append(name)
        elif name in contract['protected_files']:
            raise ValueError('protected base file missing')
        else:
            changed_code.append(name)
    if not changed_code:
        raise ValueError('new product code required; new test files present=' + str(len(new_tests)))
    if not new_tests:
        raise ValueError('new test files required; changed product files present=' + str(len(changed_code)))
    required = [item for item in os.environ.get('REQUIRED_TESTS', '').split(',') if item]
    if any(not re.fullmatch(r'test_[A-Za-z0-9_]{1,100}', item) for item in required):
        raise ValueError('invalid required test name')
    missing = sorted(set(required) - {Path(name).stem for name in new_tests})
    if missing:
        return {'error': 'required_test_missing', 'missing': missing}
    return {'mode': 'portable',
            'base_manifest_sha256': hashlib.sha256(regular_within(BASE, 'manifest.json')).hexdigest(),
            'baseline_test_sha256': {name: base_manifest['files'][name]
                                    for name in contract['test_files'] if name in base_manifest['files']},
            'new_test_sha256': {name: manifest['files'][name]['sha256'] for name in new_tests},
            'manifest_sha256': hashlib.sha256(manifest_bytes).hexdigest(),
            'diagnostic_file_sha256': {name: manifest['files'][name]['sha256']
                for name in names if name.endswith('.py') and not any(
                    is_test_path(name, root, contract['test_command'][0])
                    for root in contract['test_roots'])},
            'baseline_tests_intact': True,
            'test_image': contract['test_image'],
            'test_command': contract['test_command'],
            'test_success_pattern': contract['test_success_pattern'],
            'test_count_pattern': contract['test_count_pattern'],
            'test_files': contract['test_files'],
            'minimum_tests': len(contract['test_files'])}


if __name__ == '__main__':
    try:
        result = verify()
        print(json.dumps(result, sort_keys=True), flush=True)
        raise SystemExit(2 if result.get('error') else 0)
    except Exception as error:
        print(json.dumps({'error': 'validation_failed', 'category': type(error).__name__}), flush=True)
        raise SystemExit(1)
