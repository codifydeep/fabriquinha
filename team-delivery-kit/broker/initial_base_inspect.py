"""Fixed offline inspection of the original operator-owned base (hashes only)."""
import hashlib
import json
import os
from pathlib import Path
from portable_contract import validate,is_test_path
try:
    from incremental_base import _bytes
except ImportError:
    from broker.incremental_base import _bytes


def inspect(root,expected):
    root=Path(root)
    raw=_bytes(root,'manifest.json')
    if hashlib.sha256(raw).hexdigest()!=expected:raise ValueError('original base manifest drift')
    manifest=json.loads(raw)
    if set(manifest)!={'base_sha','files'} or not isinstance(manifest['files'],dict):
        raise ValueError('original base schema required')
    encoded=_bytes(root,'contract.json');contract=validate(json.loads(encoded))
    if manifest['files'].get('contract.json')!=hashlib.sha256(encoded).hexdigest():
        raise ValueError('operator contract changed')
    actual={str(p.relative_to(root)) for p in root.rglob('*') if p.is_file() or p.is_symlink()}
    if actual!=set(manifest['files'])|{'manifest.json'}:raise ValueError('unexpected original base entry')
    if not set(manifest['files'])<=set(contract['files'])|{'contract.json'}:
        raise ValueError('base outside approved contract')
    for name,sha in manifest['files'].items():
        if hashlib.sha256(_bytes(root,name)).hexdigest()!=sha:raise ValueError('original base file drift')
    tests={n:sha for n,sha in manifest['files'].items() if any(
        is_test_path(n,r,contract['test_command'][0]) for r in contract['test_roots'])}
    if not tests or not set(tests)<=set(contract['test_files'])&set(contract['protected_files']):
        raise ValueError('complete protected baseline test inventory required')
    return dict(base_sha=manifest['base_sha'],manifest_sha256=expected,
        baseline_test_sha256=tests,contract_sha256=hashlib.sha256(encoded).hexdigest(),
        test_image=contract['test_image'],test_command=contract['test_command'],
        test_roots=contract['test_roots'],test_files=sorted(tests),minimum_tests=len(tests),
        test_count_pattern=contract['test_count_pattern'],test_success_pattern=contract['test_success_pattern'])


if __name__=='__main__':
    print(json.dumps(inspect('/base',os.environ['EXPECTED_BASE_MANIFEST_SHA256']),sort_keys=True))
