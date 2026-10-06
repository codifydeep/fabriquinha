"""Fixed offline proof: all base bytes intact and declared new tests empty."""
import hashlib
import json
from pathlib import Path
try:
    from initial_base_inspect import inspect
    from incremental_base import _bytes
except ImportError:
    from broker.initial_base_inspect import inspect
    from broker.incremental_base import _bytes


def inspect_unwritten(base,workspace,expected,new_tests,seed=None,seed_hashes=None):
    base,workspace=Path(base),Path(workspace)
    proof=inspect(base,expected);manifest=json.loads(_bytes(base,'manifest.json'))
    existing=set(manifest['files'])-{'contract.json'}
    contract=json.loads(_bytes(base,'contract.json'))
    if not new_tests or set(new_tests)&existing or not set(new_tests)<=set(contract['test_files']):
        raise ValueError('declared new tests required')
    actual={str(p.relative_to(workspace)) for p in workspace.rglob('*') if p.is_file() or p.is_symlink()}
    marker='.delivery-kit-base.json'
    if actual!=existing|set(new_tests)|{marker}:raise ValueError('unwritten workspace layout changed')
    if json.loads(_bytes(workspace,marker))!=dict(base_sha=proof['base_sha'],manifest_sha256=expected):
        raise ValueError('unwritten workspace identity changed')
    # Validate ALL old files before checking empty new tests.
    for name in sorted(existing):
        if _bytes(workspace,name)!=_bytes(base,name):raise ValueError('base changed before recovery')
    if seed is not None:
        if not isinstance(seed_hashes,dict) or set(seed_hashes)!=set(new_tests):
            raise ValueError('exact historic NEW test inventory required')
        for name in new_tests:
            previous=_bytes(Path(seed),name)
            if hashlib.sha256(previous).hexdigest()!=seed_hashes[name]:
                raise ValueError('historic NEW test seed hash drift')
            if _bytes(workspace,name)!=previous:
                raise ValueError('seeded NEW test changed before recovery')
    else:
        if seed_hashes is not None:raise ValueError('seed root required')
        for name in new_tests:
            if _bytes(workspace,name)!=b'':raise ValueError('artifact exists; pretool recovery forbidden')
    return dict(base_manifest_sha256=expected,baseline_test_sha256=proof['baseline_test_sha256'],
        new_test_sha256=seed_hashes if seed is not None else {n:hashlib.sha256(b'').hexdigest() for n in new_tests},
        base_files_verified=len(existing),provenance='controller_offline_unchanged_seeded_workspace_v1'
        if seed is not None else 'controller_offline_unwritten_workspace_v1',delivery_approval=False)
