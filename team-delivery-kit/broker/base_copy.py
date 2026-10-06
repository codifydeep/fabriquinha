"""Idempotent operator-side copy of a verified Git tree to one base volume."""
import json
from pathlib import Path

from portable_contract import validate

SOURCE = Path('/source')
TARGET = Path('/target')
FILES = ('AGENTS.md', 'calc.py', 'test_calc.py', 'manifest.json')


def main():
    portable = SOURCE / 'contract.json'
    if portable.exists():
        contract = validate(json.loads(portable.read_text()))
        manifest = json.loads((SOURCE / 'manifest.json').read_text())
        if (set(manifest) != {'base_sha', 'files'} or not isinstance(manifest['files'], dict)
                or not set(manifest['files']) <= set(contract['files']) | {'contract.json'}
                or 'contract.json' not in manifest['files']):
            raise ValueError('invalid portable base manifest')
        names = set(manifest['files']) | {'manifest.json'}
    else:
        names = set(FILES)
    existing = {str(path.relative_to(TARGET)) for path in TARGET.rglob('*')
                if path.is_file() or path.is_symlink()}
    if not existing <= names:
        raise ValueError('foreign base volume')
    if any((TARGET / name).is_symlink() or (TARGET / name).read_bytes() != (SOURCE / name).read_bytes()
           for name in existing):
        raise ValueError('existing base content differs')
    for name in names:
        if name in existing:
            continue
        source = SOURCE / name
        if source.is_symlink() or not source.is_file():
            raise ValueError('invalid source base file')
        target = TARGET / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
        target.chmod(0o444)


if __name__ == '__main__':
    main()
