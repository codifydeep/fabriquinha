"""Fixed offline read of a registered base; no inferred contract or edit grant."""
import hashlib
import json
import os
import re
from pathlib import Path
from portable_contract import validate,MAX_FILES,MAX_FILE_BYTES
try:
    from .product_scope_materialize import safe_file
    from .product_scope_revision import digest
except ImportError:
    from product_scope_materialize import safe_file
    from product_scope_revision import digest


def read(root,name):
    path=safe_file(root,name)
    if not path.is_file() or path.stat().st_size>MAX_FILE_BYTES:raise ValueError('bounded regular scope base artifact required')
    return path.read_bytes()


def inspect(base,base_sha,manifest_sha256,contract_sha256):
    base=Path(base)
    if (not isinstance(base_sha,str) or not re.fullmatch(r'[a-f0-9]{40}',base_sha)
            or any(not isinstance(v,str) or not re.fullmatch(r'[a-f0-9]{64}',v) for v in (manifest_sha256,contract_sha256))):
        raise ValueError('exact registered base identities required')
    encoded=read(base,'manifest.json')
    if hashlib.sha256(encoded).hexdigest()!=manifest_sha256:raise ValueError('registered base manifest changed')
    manifest=json.loads(encoded)
    if (not isinstance(manifest,dict) or set(manifest)!={'base_sha','files'} or manifest['base_sha']!=base_sha
            or not isinstance(manifest['files'],dict) or not 1<=len(manifest['files'])<=MAX_FILES
            or 'contract.json' not in manifest['files']):raise ValueError('registered portable base required')
    contract=validate(json.loads(read(base,'contract.json')))
    if digest(contract)!=contract_sha256 or not set(manifest['files'])<=set(contract['files'])|{'contract.json'}:
        raise ValueError('installed contract differs from registered route')
    for name,sha in manifest['files'].items():
        if hashlib.sha256(read(base,name)).hexdigest()!=sha:raise ValueError('original baseline file changed')
    names=set(manifest['files'])|{'manifest.json'}
    for path in base.rglob('*'):
        relative=str(path.relative_to(base))
        if path.is_symlink() or path.is_file() and relative not in names:raise ValueError('foreign scope base artifact')
        if path.is_dir() and not any(n.startswith(relative+'/') for n in names):raise ValueError('foreign scope base directory')
    return dict(operation='inspected_product_scope_base_v1',base_sha=base_sha,manifest_sha256=manifest_sha256,
                contract_sha256=contract_sha256,contract=contract,write_grant_issued=False,delivery_approval=False)


def main():
    print(json.dumps(inspect('/base',os.environ['BASE_SHA'],os.environ['BASE_MANIFEST_SHA256'],
                             os.environ['CONTRACT_SHA256']),sort_keys=True,separators=(',',':')),flush=True)


if __name__=='__main__':main()
