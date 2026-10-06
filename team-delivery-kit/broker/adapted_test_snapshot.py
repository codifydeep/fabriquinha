"""Controller-only immutable NEW-test projection, separate from native artifacts.

No old task, Red or approval is overwritten. The controller separately validates
CTO sponsorship and volume ownership before running this fixed offline job.
"""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import uuid

from portable_contract import safe_path, validate
try:
    from framework_mark_diagnosis import adapt_required_node
    from test_first_protocol import prepare_red, _regular
except ImportError:
    from broker.framework_mark_diagnosis import adapt_required_node
    from broker.test_first_protocol import prepare_red, _regular


def materialize(base, source, destination, selection):
    base, source, destination = map(Path, (base, source, destination))
    keys = {'revision_id', 'path', 'original_sha256', 'expected_candidate_sha256',
            'base_manifest_sha256', 'source_manifest_sha256'}
    if not isinstance(selection, dict) or set(selection) != keys:
        raise ValueError('exact adapted revision selection required')
    if str(uuid.UUID(selection['revision_id'])) != selection['revision_id']:
        raise ValueError('canonical adapted revision identity required')
    name = selection['path']; safe_path(name)
    contract = validate(json.loads(_regular(base, 'contract.json')))
    base_raw = _regular(base, 'manifest.json'); source_raw = _regular(source, 'manifest.json')
    if (hashlib.sha256(base_raw).hexdigest() != selection['base_manifest_sha256']
            or hashlib.sha256(source_raw).hexdigest() != selection['source_manifest_sha256']):
        raise ValueError('adapted revision input manifest drift')
    base_manifest = json.loads(base_raw); source_manifest = json.loads(source_raw)
    if set(source_manifest) != {'files'} or set(base_manifest) != {'base_sha', 'files'}:
        raise ValueError('adapted revision manifest shape drift')
    baseline = set(base_manifest['files']) - {'contract.json'}
    if (name in baseline or name not in contract['test_files'] or name not in contract['editable_files']
            or set(source_manifest['files']) != baseline | {name}):
        raise ValueError('only declared NEW test may be adapted')
    actual = {str(p.relative_to(source)) for p in source.rglob('*') if p.is_file() or p.is_symlink()}
    if actual != baseline | {name, 'manifest.json'}:
        raise ValueError('adapted revision source layout drift')
    if destination.is_symlink() or any(p.is_symlink() for p in destination.rglob('*')):
        raise ValueError('adapted revision destination symlink')
    contents = {}
    for file in sorted(baseline | {name}):
        data = _regular(source, file)
        if source_manifest['files'][file] != {'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}:
            raise ValueError('adapted revision source hash drift')
        if (source/file).stat().st_nlink != 1:
            raise ValueError('adapted revision source hardlink')
        if file in baseline and (data != _regular(base, file)
                or hashlib.sha256(data).hexdigest() != base_manifest['files'][file]):
            raise ValueError('adapted revision baseline changed')
        contents[file] = data
    candidate, transform = adapt_required_node(contents[name], selection['original_sha256'])
    if hashlib.sha256(candidate).hexdigest() != selection['expected_candidate_sha256']:
        raise ValueError('adapted revision candidate hash drift')
    contents[name] = candidate
    # Construct only in disposable storage; original snapshot is never writable.
    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        for file, data in contents.items():
            target = workspace/file; target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        prepared = prepare_red(base, workspace, destination, contract, resume=True)
    # prepare_red is a snapshot operation, NOT assess_red or a Red receipt.
    for path in destination.rglob('*'):
        if path.is_file():
            if path.stat().st_nlink != 1:
                raise ValueError('adapted revision destination hardlink')
            path.chmod(0o400)
            with path.open('rb') as stream:
                os.fsync(stream.fileno())
    for directory in [destination] + [p for p in destination.rglob('*') if p.is_dir()]:
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try: os.fsync(fd)
        finally: os.close(fd)
    return dict(operation='immutable_adapted_new_test_revision_v1',
        revision_id=selection['revision_id'], source_manifest_sha256=selection['source_manifest_sha256'],
        prepared=prepared, transform=transform, baseline_unchanged=True,
        delivery_approval=False, red_evidence=False)


if __name__ == '__main__':
    print(json.dumps(materialize('/base', '/source', '/snapshot',
                                json.loads(os.environ['ADAPTED_SELECTION'])), sort_keys=True))
