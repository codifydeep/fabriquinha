"""Fixed, offline copy of the disposable TDD artifact into a snapshot volume."""
import hashlib
import json
import os
from pathlib import Path

from portable_contract import validate, required_files, MAX_FILE_BYTES

SOURCE = Path('/workspace')
DESTINATION = Path('/snapshot')
BASE = Path('/base')
FILES = ('AGENTS.md', 'calc.py', 'test_calc.py')


def main():
    if any(DESTINATION.iterdir()) and os.environ.get('SNAPSHOT_RESUME') != '1':
        raise ValueError('snapshot destination is not empty')
    portable = BASE / 'contract.json'
    contract = validate(json.loads(portable.read_text())) if portable.exists() else None
    names = tuple(contract['files']) if contract else FILES
    required = required_files(contract) if contract else set(FILES)
    if contract:
        required |= set(json.loads((BASE / 'manifest.json').read_text())['files']) - {'contract.json'}
    missing = sorted(name for name in required if not (SOURCE / name).exists())
    if missing:
        print(json.dumps({'error': 'required_artifact_missing', 'missing': missing}), flush=True)
        raise ValueError('required artifact missing')
    existing = {str(p.relative_to(DESTINATION)) for p in DESTINATION.rglob('*')
                if p.is_file() or p.is_symlink()}
    if not existing <= set(names) | {'manifest.json'}:
        raise ValueError('unexpected snapshot contents')
    manifest = {}
    for name in names:
        source = SOURCE / name
        if name not in required and not source.exists() and not source.is_symlink():
            continue
        parents = list(source.parents)[:len(Path(name).parts) - 1]
        if (source.is_symlink() or any(parent.is_symlink() for parent in parents)
                or not source.is_file() or source.stat().st_size > MAX_FILE_BYTES):
            raise ValueError('invalid source artifact')
        content = source.read_bytes()
        manifest[name] = {'sha256': hashlib.sha256(content).hexdigest(), 'bytes': len(content)}
        target = DESTINATION / name
        if target.is_symlink() or any(p.is_symlink() for p in list(target.parents)[:len(Path(name).parts)-1]):
            raise ValueError('snapshot symlink')
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if target.read_bytes() != content:
                raise ValueError('interrupted snapshot differs from source')
        else:
            with os.fdopen(os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400), 'wb') as stream:
                stream.write(content)
    encoded = json.dumps({'files': manifest}, sort_keys=True, separators=(',', ':')).encode()
    target = DESTINATION / 'manifest.json'
    if target.is_symlink():
        raise ValueError('snapshot manifest symlink')
    if target.exists():
        if target.read_bytes() != encoded:
            raise ValueError('snapshot manifest changed')
    else:
        with os.fdopen(os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400), 'wb') as stream:
            stream.write(encoded)


if __name__ == '__main__':
    main()
