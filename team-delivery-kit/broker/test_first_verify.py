"""Offline Docker entrypoint: verify final delivery retained frozen Red tests."""
import json
import os
import hashlib
from pathlib import Path

from portable_contract import safe_path
from test_first_protocol import verify_green_tests


def main():
    hashes = json.loads(os.environ['TEST_FIRST_TEST_HASHES'])
    if not isinstance(hashes, dict) or not hashes:
        raise ValueError('missing test-first hashes')
    manifest = Path('/red/manifest.json').read_bytes()
    if hashlib.sha256(manifest).hexdigest() != os.environ['TEST_FIRST_RED_MANIFEST_SHA256']:
        raise ValueError('Red snapshot manifest changed')
    declared = json.loads(manifest)['files']
    for name in hashes:
        safe_path(name)
    if any(declared.get(name, {}).get('sha256') != digest
           or hashlib.sha256((Path('/red') / name).read_bytes()).hexdigest() != digest
           for name, digest in hashes.items()):
        raise ValueError('Red snapshot test changed')
    verify_green_tests('/delivery', {'test_sha256': hashes})
    print(json.dumps({'tests_unchanged': True, 'count': len(hashes)}), flush=True)


if __name__ == '__main__':
    main()
