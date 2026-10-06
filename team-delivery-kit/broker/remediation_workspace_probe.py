"""Fixed credential-free base copy and preserved-test seed qualification."""
import hashlib
import json
import os
import stat
from pathlib import Path
try:
    import base_copy,seed_workspace
    from initial_base_inspect import inspect
except ImportError:
    from broker import base_copy,seed_workspace
    from broker.initial_base_inspect import inspect


def copy_original(source,target,expected):
    before=inspect(source,expected)
    old=base_copy.SOURCE,base_copy.TARGET
    try:
        base_copy.SOURCE,base_copy.TARGET=Path(source),Path(target);base_copy.main()
        if inspect(target,expected)!=before or inspect(source,expected)!=before:raise ValueError('copied original base mismatch')
        return dict(operation='remediation_original_base_copy_v2',base_sha=before['base_sha'],manifest_sha256=expected,
            baseline_test_sha256=before['baseline_test_sha256'],contract_sha256=before['contract_sha256'],
            baseline_unchanged=True,product_unchanged=True,red_executed=False,execution_authorized=False)
    finally:base_copy.SOURCE,base_copy.TARGET=old


def prepare(source,target,previous,work,expected,selection,*,copy=True):
    before=inspect(source,expected)
    snapshot_paths=['manifest.json',*sorted(selection['test_sha256'])]
    permissions={name:(Path(previous)/name).stat() for name in snapshot_paths}
    metadata={name:dict(uid=s.st_uid,gid=s.st_gid,mode=stat.S_IMODE(s.st_mode)) for name,s in permissions.items()}
    old=(base_copy.SOURCE,base_copy.TARGET,seed_workspace.BASE,seed_workspace.PREVIOUS,seed_workspace.WORK)
    prior={key:os.environ.get(key) for key in ('BASE_MANIFEST_SHA256','REVISION_SEED_JSON')}
    try:
        if copy:
            base_copy.SOURCE,base_copy.TARGET=Path(source),Path(target)
            base_copy.main()
        copied=inspect(target,expected)
        if copied!=before:raise ValueError('copied original base mismatch')
        seed_workspace.BASE,seed_workspace.PREVIOUS,seed_workspace.WORK=Path(target),Path(previous),Path(work)
        os.environ['BASE_MANIFEST_SHA256']=expected;os.environ['REVISION_SEED_JSON']=json.dumps(selection)
        seed_workspace.main()
        manifest=json.loads((Path(target)/'manifest.json').read_text())
        expected_files={k:v for k,v in manifest['files'].items() if k!='contract.json'}
        expected_files.update(selection['test_sha256'])
        actual={str(p.relative_to(work)) for p in Path(work).rglob('*') if p.is_file() or p.is_symlink()}
        if actual!=set(expected_files)|{'.delivery-kit-base.json'}:raise ValueError('unexpected seeded workspace file')
        for name,sha in expected_files.items():
            path=Path(work)/name
            if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest()!=sha:raise ValueError('seeded workspace hash mismatch')
        if inspect(source,expected)!=before or inspect(target,expected)!=before:raise ValueError('original base mutated during qualification')
        for name,original in metadata.items():
            s=(Path(previous)/name).stat()
            if dict(uid=s.st_uid,gid=s.st_gid,mode=stat.S_IMODE(s.st_mode))!=original:
                raise ValueError('preserved snapshot permissions changed')
        return dict(operation='remediation_original_base_seed_v1',base_sha=before['base_sha'],manifest_sha256=expected,
            baseline_test_sha256=before['baseline_test_sha256'],contract_sha256=before['contract_sha256'],
            previous_manifest_sha256=selection['manifest_sha256'],seed_test_sha256=selection['test_sha256'],
            workspace_files=len(expected_files),product_unchanged=True,baseline_unchanged=True,
            snapshot_permissions_unchanged=True,snapshot_metadata=metadata,
            red_executed=False,execution_authorized=False,release_homologated=False)
    finally:
        base_copy.SOURCE,base_copy.TARGET,seed_workspace.BASE,seed_workspace.PREVIOUS,seed_workspace.WORK=old
        for key,value in prior.items():
            if value is None:os.environ.pop(key,None)
            else:os.environ[key]=value


if __name__=='__main__':
    import sys
    if sys.argv[1:]==['copy']:
        proof=copy_original('/source','/target',os.environ['EXPECTED_BASE_MANIFEST_SHA256'])
    elif sys.argv[1:]==['seed']:
        proof=prepare('/source','/target','/previous','/workspace',os.environ['EXPECTED_BASE_MANIFEST_SHA256'],
                      json.loads(os.environ['REVISION_SEED_JSON']),copy=False)
    else:raise ValueError('fixed copy or seed operation required')
    print(json.dumps(proof,sort_keys=True))
