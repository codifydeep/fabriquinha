"""Controller-only filesystem fence for one isolated implementation workspace.

Run as root in a short-lived, socketless container. The agent runs as UID 10000
without capabilities, so ACP, Python and terminal tools see the same file fence.
"""
import hashlib
import json
import os
from pathlib import Path

from portable_contract import validate


BASE = Path('/base')
WORK = Path('/workspace')


def _regular(path, limit=32768):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise ValueError('unsafe workspace file: ' + str(path))
    return path.read_bytes()


def lockdown(base, work, allowed, repair=None):
    base, work = Path(base), Path(work)
    contract = validate(json.loads(_regular(base / 'contract.json')))
    manifest_bytes = _regular(base / 'manifest.json')
    manifest = json.loads(manifest_bytes)
    if (set(manifest) != {'base_sha', 'files'}
            or manifest['files'].get('contract.json') != hashlib.sha256(
                _regular(base / 'contract.json')).hexdigest()):
        raise ValueError('workspace base identity mismatch')
    if (not isinstance(allowed, list) or not allowed
            or len(allowed) != len(set(allowed))
            or not set(allowed) <= set(contract['editable_files'])):
        raise ValueError('workspace edit scope is not in contract')
    names = set(contract['files'])
    baseline = set(manifest['files']) - {'contract.json'}
    if not baseline <= names:
        raise ValueError('workspace base outside contract')
    repair = repair or {}
    if (not isinstance(repair, dict) or not set(repair) <= set(allowed)-baseline
            or not set(repair) <= set(contract['test_files'])
            or any(not isinstance(v, dict) or set(v) != {'bytes','sha256'}
                   or type(v['bytes']) is not int or not 32768 < v['bytes'] <= 65536
                   for v in repair.values())):
        raise ValueError('invalid historical repair lockdown input')
    marker = work / '.delivery-kit-base.json'
    if json.loads(_regular(marker)) != {
            'base_sha': manifest['base_sha'],
            'manifest_sha256': hashlib.sha256(manifest_bytes).hexdigest()}:
        raise ValueError('workspace base marker mismatch')
    # Reject unexpected entries before changing permissions. A failed task may
    # require an operator-owned cleanup; an agent cannot silently hide debris.
    for path in work.rglob('*'):
        name = str(path.relative_to(work))
        if path.is_symlink() or (not path.is_file() and not path.is_dir()):
            raise ValueError('unsafe workspace entry: ' + name)
        if path.is_file() and name not in names | {marker.name}:
            raise ValueError('undeclared workspace file: ' + name)
        if path.is_dir() and not any(item.startswith(name + '/') for item in names):
            raise ValueError('undeclared workspace directory: ' + name)
    for name in baseline:
        if not (work / name).is_file() or (work / name).is_symlink():
            raise ValueError('missing baseline workspace file: ' + name)
    for name in allowed:
        target = work / name
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            with os.fdopen(os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb'):
                pass
        bound=repair.get(name)
        content=_regular(target, bound['bytes'] if bound else 32768)
        if len(content)>32768 and (len(content)!=bound['bytes']
                or hashlib.sha256(content).hexdigest()!=bound['sha256']):
            raise ValueError('historical repair lockdown hash drift')
    # Root owns every directory and file. Only the exact selected regular
    # files receive write bits; a worker cannot rename them or create siblings.
    for path in sorted(work.rglob('*'), key=lambda item: len(item.parts), reverse=True):
        if path.is_symlink():
            raise ValueError('workspace symlink')
        os.chown(path, 0, 0)
        if path.is_dir():
            os.chmod(path, 0o555)
        elif path.is_file():
            os.chmod(path, 0o666 if str(path.relative_to(work)) in allowed else 0o444)
        else:
            raise ValueError('unsafe workspace object')
    os.chown(work, 0, 0)
    os.chmod(work, 0o555)
    return {'allowed': sorted(allowed), 'baseline_files': len(baseline)}


def main():
    allowed = json.loads(os.environ['WORKSPACE_ALLOWED_JSON'])
    repair=json.loads(os.environ.get('WORKSPACE_REPAIR_INPUT_JSON','{}'))
    print(json.dumps(lockdown(BASE, WORK, allowed,repair), sort_keys=True), flush=True)


if __name__ == '__main__':
    main()
