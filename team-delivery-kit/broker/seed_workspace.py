"""Idempotently seed one issue workspace from a controller-owned Git base."""
import hashlib
import json
import os
from pathlib import Path

from portable_contract import validate, safe_path

BASE = Path('/base')
WORK = Path('/workspace')
PREVIOUS = Path('/previous')
FILES = ('AGENTS.md', 'calc.py', 'test_calc.py')


def revision_contents(contract, baseline):
    """Read only controller-selected NEW tests from a hash-bound frozen Red."""
    raw = os.environ.get('REVISION_SEED_JSON')
    if raw is None:
        return {}
    selection = json.loads(raw)
    if (not contract or not isinstance(selection, dict)
            or set(selection) not in ({'manifest_sha256', 'test_sha256'},
                                      {'manifest_sha256','test_sha256','repair_input_bytes'})
            or not isinstance(selection['test_sha256'], dict) or not selection['test_sha256']):
        raise ValueError('invalid revision seed selection')
    names = set(selection['test_sha256'])
    if (names & set(baseline) or not names <= set(contract['test_files']) & set(contract['editable_files'])):
        raise ValueError('revision seed may only copy declared NEW tests')
    repair=selection.get('repair_input_bytes',{})
    if (not isinstance(repair,dict) or not set(repair)<=names
            or any(type(v) is not int or not 32768<v<=65536 for v in repair.values())):
        raise ValueError('bounded historical repair input required')
    def read(name):
        safe_path(name)
        path = PREVIOUS / name
        limit=repair.get(name,32768)
        if (path.is_symlink() or not path.is_file() or path.stat().st_size > limit
                or any(parent.is_symlink() for parent in
                       list(path.parents)[:len(Path(name).parts) - 1])):
            raise ValueError('unsafe revision seed file')
        return path.read_bytes()
    encoded = read('manifest.json')
    if hashlib.sha256(encoded).hexdigest() != selection['manifest_sha256']:
        raise ValueError('revision seed manifest mismatch')
    frozen = json.loads(encoded)
    result = {}
    for name in names:
        data = read(name)
        if name in repair and len(data)!=repair[name]:
            raise ValueError('historical repair input byte drift')
        digest = hashlib.sha256(data).hexdigest()
        if (digest != selection['test_sha256'][name]
                or frozen['files'].get(name) != {'sha256': digest, 'bytes': len(data)}):
            raise ValueError('revision seed test hash mismatch')
        result[name] = data
    return result


def main():
    manifest = json.loads((BASE / 'manifest.json').read_text())
    portable = BASE / 'contract.json'
    contract = None
    if portable.exists():
        contract = validate(json.loads(portable.read_text()))
        if (hashlib.sha256(portable.read_bytes()).hexdigest() != manifest['files'].get('contract.json')
                or not set(manifest['files']) <= set(contract['files']) | {'contract.json'}):
            raise ValueError('portable contract identity mismatch')
        names = tuple(name for name in manifest['files'] if name != 'contract.json')
    else:
        names = FILES
    if set(manifest) != {'base_sha', 'files'} or set(manifest['files']) != set(names) | ({'contract.json'} if portable.exists() else set()):
        raise ValueError('invalid base manifest')
    digest = hashlib.sha256((BASE / 'manifest.json').read_bytes()).hexdigest()
    if digest != os.environ['BASE_MANIFEST_SHA256']:
        raise ValueError('base manifest identity mismatch')
    for name in names:
        source = BASE / name
        if source.is_symlink() or not source.is_file():
            raise ValueError('invalid base file')
        content = source.read_bytes()
        if len(content) > 32768 or hashlib.sha256(content).hexdigest() != manifest['files'][name]:
            raise ValueError('base hash mismatch')
    revised = revision_contents(contract, names)
    marker = WORK / '.delivery-kit-base.json'
    if marker.exists():
        if json.loads(marker.read_text()) != {'base_sha': manifest['base_sha'], 'manifest_sha256': digest}:
            raise ValueError('workspace already belongs to another base')
        return
    # A retry can safely overwrite an interrupted first seed; no worker is
    # dispatched until the marker has been written and verified.
    if any(path.is_symlink() for path in WORK.rglob('*')):
        raise ValueError('workspace symlink')
    present = {str(p.relative_to(WORK)) for p in WORK.rglob('*') if p.is_file() or p.is_symlink()}
    if present - set(names) - set(revised) - {'.delivery-kit-base.tmp'}:
        raise ValueError('unexpected workspace contents before first seed')
    contents = {name: (BASE / name).read_bytes() for name in names}
    contents.update(revised)
    # Validate every destination before copying anything, including parent dirs.
    for name in contents:
        target = WORK / name
        if target.is_symlink() or any(parent.is_symlink() for parent in
                                     list(target.parents)[:len(Path(name).parts) - 1]):
            raise ValueError('workspace symlink')
    for name, data in contents.items():
        target = WORK / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        os.chmod(target, 0o644)
    temporary = WORK / '.delivery-kit-base.tmp'
    temporary.write_text(json.dumps({'base_sha': manifest['base_sha'], 'manifest_sha256': digest}))
    os.chmod(temporary, 0o444)
    os.replace(temporary, marker)


if __name__ == '__main__':
    main()
