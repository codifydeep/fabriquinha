"""Fixed read-only verification before registering a materialized scope base."""
import hashlib
import json
import os
from pathlib import Path
try:
    from .product_scope_materialize import qualified_contract,safe_file,encoded
except ImportError:
    from product_scope_materialize import qualified_contract,safe_file,encoded


def sha(value):return hashlib.sha256(value).hexdigest()


def read(root,name):
    path=safe_file(root,name)
    if not path.is_file():raise ValueError('required scope base file missing')
    return path.read_bytes()


def verify(base,revision,state,original_manifest_sha256,receipt):
    base,revision=Path(base),Path(revision)
    contract,_=qualified_contract(state)
    original_bytes=read(base,'manifest.json')
    if sha(original_bytes)!=original_manifest_sha256:raise ValueError('original base manifest changed')
    original=json.loads(original_bytes)
    if (not isinstance(original,dict) or set(original)!={'base_sha','files'}
            or not isinstance(original['files'],dict) or 'contract.json' not in original['files']
            or not set(original['files'])<=set(contract['files'])|{'contract.json'}):
        raise ValueError('original registered portable base required')
    contract_bytes=encoded(contract)
    expected=dict(base_sha=original['base_sha'],files=dict(original['files'],**{'contract.json':sha(contract_bytes)}))
    manifest_bytes=read(revision,'manifest.json')
    if (manifest_bytes!=encoded(expected) or sha(manifest_bytes)!=receipt['manifest_sha256']
            or sha(contract_bytes)!=receipt['contract_sha256'] or original['base_sha']!=receipt['base_sha']
            or receipt['original_base_manifest_sha256']!=original_manifest_sha256
            or receipt['frozen_test_sha256']!=state['context']['frozen_test_sha256']
            or any(receipt[k] is not False for k in ('write_grant_issued','delivery_approval','historical_red_recreated'))):
        raise ValueError('exact materialized manifest and unchanged evidence bindings required')
    for name,digest in original['files'].items():
        data=read(base,name)
        if sha(data)!=digest:raise ValueError('original baseline file changed')
        if name=='contract.json':
            if json.loads(data)!=state['original_contract']:raise ValueError('original contract changed')
            data=contract_bytes
        if read(revision,name)!=data:raise ValueError('materialized base changed code or tests')
    names=set(expected['files'])|{'manifest.json'}
    for path in revision.rglob('*'):
        relative=str(path.relative_to(revision))
        if path.is_symlink() or (path.is_file() and relative not in names):raise ValueError('foreign revision artifact')
        if path.is_dir() and not any(n.startswith(relative+'/') for n in names):raise ValueError('foreign revision directory')
    return dict(operation='verified_product_scope_base_v1',base_sha=original['base_sha'],
        original_base_manifest_sha256=original_manifest_sha256,manifest_sha256=sha(manifest_bytes),
        contract_sha256=sha(contract_bytes),frozen_test_sha256=state['context']['frozen_test_sha256'],
        delivery_approval=False,write_grant_issued=False)


def main():
    print(json.dumps(verify('/base','/revision',json.loads(os.environ['PRODUCT_SCOPE_PLAN_JSON']),
        os.environ['BASE_MANIFEST_SHA256'],json.loads(os.environ['MATERIALIZATION_RECEIPT_JSON'])),
        sort_keys=True,separators=(',',':')),flush=True)


if __name__=='__main__':main()
