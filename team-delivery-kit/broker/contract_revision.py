"""Narrow technical replan: only new non-test code can become optional."""
import hashlib
import json
import os
from pathlib import Path

from portable_contract import validate, required_files


def revised(contract, baseline, optional):
    validate(contract)
    if (not isinstance(optional, list) or not optional
            or any(not isinstance(name, str) for name in optional)
            or len(set(optional)) != len(optional)):
        raise ValueError('optional files must be explicit')
    eligible = set(contract['editable_files']) - set(contract['test_files']) - set(baseline)
    if not set(optional) <= eligible:
        raise ValueError('cannot relax baseline, tests or protected files')
    result = {**contract, 'schema_version': 2,
              'required_files': sorted(required_files(contract) - set(optional))}
    return validate(result)


def main():
    base, target = Path('/base'), Path('/revision')
    old = json.loads((base / 'manifest.json').read_text())
    original = json.loads((base / 'contract.json').read_text())
    contract = revised(original, old['files'], json.loads(os.environ['OPTIONAL_FILES']))
    content = json.dumps(contract, sort_keys=True, separators=(',', ':')).encode()
    manifest = {'base_sha': old['base_sha'], 'files': {**old['files'],
                'contract.json': hashlib.sha256(content).hexdigest()}}
    encoded = json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode()
    for name, digest in old['files'].items():
        source = base / name
        if source.is_symlink() or hashlib.sha256(source.read_bytes()).hexdigest() != digest:
            raise ValueError('original base hash mismatch')
        data = content if name == 'contract.json' else source.read_bytes()
        output = target / name
        output.parent.mkdir(parents=True, exist_ok=True)
        if output.exists() and (output.is_symlink() or output.read_bytes() != data):
            raise ValueError('revision contents differ')
        if not output.exists():
            output.write_bytes(data)
            output.chmod(0o444)
    output = target / 'manifest.json'
    if output.exists() and output.read_bytes() != encoded:
        raise ValueError('revision manifest differs')
    if not output.exists():
        output.write_bytes(encoded)
        output.chmod(0o444)
    print(json.dumps({'contract': contract, 'contract_sha256': hashlib.sha256(content).hexdigest(),
                      'manifest_sha256': hashlib.sha256(encoded).hexdigest()}), flush=True)


if __name__ == '__main__':
    main()
