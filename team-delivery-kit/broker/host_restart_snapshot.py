"""Fixed pre-Red preservation job. Its output is never TDD evidence."""
import hashlib
import json
import os
from pathlib import Path
from portable_contract import validate


def preserve(base, workspace, snapshot):
    base, workspace, snapshot = map(Path, (base, workspace, snapshot))
    contract = validate(json.loads((base / 'contract.json').read_text()))
    original = json.loads((base / 'manifest.json').read_text())
    required = set(original['files']) - {'contract.json'}
    names = {str(p.relative_to(workspace)) for p in workspace.rglob('*')
             if p.is_file() or p.is_symlink()}
    if not required <= names or not names <= set(contract['files']) | {'.delivery-kit-base.json'}:
        raise ValueError('restart workspace scope changed')
    files = {}
    for name in sorted(names - {'.delivery-kit-base.json'}):
        source = workspace / name
        if source.is_symlink() or any(p.is_symlink() for p in list(source.parents)[:len(Path(name).parts)-1]):
            raise ValueError('restart workspace symlink')
        if source.stat().st_size > 32768:
            raise ValueError('restart artifact too large')
        raw = source.read_bytes()
        sha = hashlib.sha256(raw).hexdigest()
        if name in required and sha != original['files'][name]:
            raise ValueError('baseline changed before Red')
        files[name] = dict(bytes=len(raw), sha256=sha)
        target = snapshot / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_symlink():
            raise ValueError('restart snapshot symlink')
        if target.exists():
            if target.read_bytes() != raw:
                raise ValueError('restart snapshot drift')
        else:
            with os.fdopen(os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o400), 'wb') as out:
                out.write(raw)
    encoded = json.dumps(dict(files=files), sort_keys=True, separators=(',', ':')).encode()
    target = snapshot / 'manifest.json'
    if target.exists():
        if target.is_symlink() or target.read_bytes() != encoded:
            raise ValueError('restart manifest drift')
    else:
        with os.fdopen(os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o400), 'wb') as out:
            out.write(encoded)
    return dict(baseline_unchanged=True, manifest_sha256=hashlib.sha256(encoded).hexdigest(),
                files=len(files), delivery_approval=False, red_verified=False)


if __name__ == '__main__':
    print(json.dumps(preserve('/base', '/workspace', '/snapshot')))
