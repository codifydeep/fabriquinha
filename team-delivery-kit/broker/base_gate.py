"""Trusted preflight: frozen delivery must extend the current Git base."""
import ast
import hashlib
import json
from pathlib import Path
import re
import subprocess


FILES = ('AGENTS.md', 'calc.py', 'test_calc.py')


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args], stderr=subprocess.DEVNULL)


def test_methods(content):
    tree = ast.parse(content)
    found = {}
    for parent in tree.body:
        if not isinstance(parent, ast.ClassDef):
            continue
        for node in parent.body:
            if isinstance(node, ast.FunctionDef) and node.name.startswith('test_'):
                if node.name in found:
                    raise ValueError('duplicate test name')
                found[node.name] = ast.dump(node, include_attributes=False)
    return found


def verify_base_compatible(repo, base_sha, snapshot, current_ref='HEAD'):
    repo, snapshot = Path(repo), Path(snapshot)
    if not isinstance(base_sha, str) or not re.fullmatch(r'[0-9a-f]{40}', base_sha):
        raise ValueError('invalid base SHA')
    if current_ref not in ('HEAD', 'main'):
        raise ValueError('invalid base ref')
    if git(repo, 'rev-parse', current_ref).decode().strip() != base_sha:
        raise ValueError('base moved')
    manifest_bytes = (snapshot / 'manifest.json').read_bytes()
    manifest = json.loads(manifest_bytes)
    if set(manifest) != {'files'} or set(manifest['files']) != set(FILES):
        raise ValueError('invalid frozen manifest')
    delivery = {}
    for name in FILES:
        path = snapshot / name
        if path.is_symlink() or not path.is_file():
            raise ValueError('invalid frozen file')
        data = path.read_bytes()
        entry = manifest['files'][name]
        if entry != {'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}:
            raise ValueError('frozen manifest mismatch')
        delivery[name] = data
    base = {name: git(repo, 'show', base_sha + ':' + name) for name in FILES}
    if delivery['AGENTS.md'] != base['AGENTS.md']:
        raise ValueError('AGENTS policy changed by implementation')
    if delivery['calc.py'] == base['calc.py']:
        raise ValueError('implementation unchanged')
    before, after = test_methods(base['test_calc.py']), test_methods(delivery['test_calc.py'])
    if any(after.get(name) != body for name, body in before.items()):
        raise ValueError('pre-existing test removed or changed')
    new_tests = sorted(set(after) - set(before))
    if not new_tests:
        raise ValueError('new behavior lacks test')
    return {'base_sha': base_sha,
            'manifest_sha256': hashlib.sha256(manifest_bytes).hexdigest(),
            'new_tests': new_tests}
