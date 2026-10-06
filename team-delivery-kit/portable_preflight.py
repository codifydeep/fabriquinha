"""Verify a frozen project delivery against an immutable Git base and contract."""
import hashlib
import json
from pathlib import Path
import re
import subprocess

from portable_contract import MAX_FILE_BYTES, is_test_path, validate, validate_delivery_files


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args], stderr=subprocess.DEVNULL)


def verify(repo, base_sha, snapshot, contract, allow_advanced_main=False):
    contract = validate(contract)
    if not isinstance(base_sha, str) or not re.fullmatch(r'[0-9a-f]{40}', base_sha):
        raise ValueError('invalid base SHA')
    repo, snapshot = Path(repo), Path(snapshot)
    remote = git(repo, 'remote', 'get-url', 'origin').decode().strip()
    if remote not in ('https://github.com/' + contract['repository'] + '.git',
                      'git@github.com:' + contract['repository'] + '.git'):
        raise ValueError('repository remote differs from contract')
    if git(repo, 'rev-parse', 'main').decode().strip() != base_sha:
        if not allow_advanced_main or subprocess.run(
                ['git', '-C', str(repo), 'merge-base', '--is-ancestor', base_sha, 'main']).returncode:
            raise ValueError('base moved')
    tracked = git(repo, 'ls-tree', '-r', '--name-only', base_sha).decode().splitlines()
    baseline_test_tree = {name for name in tracked if any(
        is_test_path(name, root, contract['test_command'][0])
        for root in contract['test_roots'])}
    if not baseline_test_tree <= set(contract['protected_files']):
        raise ValueError('baseline test tree is not fully protected')
    manifest_path = snapshot / 'manifest.json'
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError('missing frozen manifest')
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    if not isinstance(manifest, dict) or set(manifest) != {'files'} or not isinstance(manifest['files'], dict):
        raise ValueError('frozen manifest file set mismatch')
    names = validate_delivery_files(contract, manifest['files'], tracked)
    actual = {str(path.relative_to(snapshot)) for path in snapshot.rglob('*') if path.is_file() or path.is_symlink()}
    if actual != set(names) | {'manifest.json'}:
        raise ValueError('unexpected frozen entry')
    changes = []
    new_tests = []
    for name in names:
        path = snapshot / name
        if path.is_symlink() or not path.is_file():
            raise ValueError('invalid frozen file')
        content = path.read_bytes()
        if len(content) > MAX_FILE_BYTES or manifest['files'][name] != {
                'sha256': hashlib.sha256(content).hexdigest(), 'bytes': len(content)}:
            raise ValueError('frozen file hash or size mismatch')
        base = subprocess.run(['git', '-C', str(repo), 'show', base_sha + ':' + name],
                              capture_output=True)
        if name in contract['protected_files']:
            if base.returncode or content != base.stdout:
                raise ValueError('protected baseline file changed: ' + name)
        elif base.returncode == 0:
            if content != base.stdout:
                changes.append(name)
            if name in contract['test_files'] and content != base.stdout:
                raise ValueError('pre-existing test file changed: ' + name)
        elif name in contract['test_files']:
            new_tests.append(name)
        else:
            changes.append(name)
    if not changes or not new_tests:
        raise ValueError('delivery requires changed code and new test files')
    return {'base_sha': base_sha,
            'manifest_sha256': hashlib.sha256(manifest_bytes).hexdigest(),
            'changed_code': sorted(changes), 'new_test_files': sorted(new_tests)}
