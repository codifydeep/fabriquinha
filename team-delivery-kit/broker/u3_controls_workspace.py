"""Controller-derived maintenance fixture, explicitly NOT a new Git commit."""
import hashlib,json
from pathlib import Path
from portable_contract import validate
from maintenance_snapshot_validate import manifest

def main():
    import os
    seed=Path('/seed');target=Path('/revision');base=Path('/base')
    raw,files=manifest(seed)
    if hashlib.sha256(raw).hexdigest()!=os.environ['SEED_MANIFEST']:raise ValueError('verified seed required')
    path=os.environ['NEW_TEST'];contract=json.loads((base/'contract.json').read_text())
    contract['files']=sorted(set(files)|{path})
    # Legacy portable contract needs a declared code file; it is NOT in the
    # worker's edit grant, and controller validation freezes every seed file.
    contract['protected_files']=sorted(set(files)-{'app/static/app.js'})
    contract['editable_files']=[path,'app/static/app.js']
    contract['test_files']=sorted((set(contract['test_files'])&set(files))|{path,'tests/test_incremental_u3.py'})
    if contract['schema_version']==2:contract['required_files']=contract['files']
    validate(contract)
    contents={p:(seed/p).read_bytes() for p in files}
    contents['contract.json']=json.dumps(contract,sort_keys=True).encode()
    metadata={'base_sha':os.environ['BASE_SHA'],'files':{p:hashlib.sha256(v).hexdigest() for p,v in contents.items()}}
    contents['manifest.json']=json.dumps(metadata,sort_keys=True).encode()
    existing={str(p.relative_to(target)) for p in target.rglob('*') if p.is_file() or p.is_symlink()}
    if not existing<=set(contents):raise ValueError('foreign fixture entries')
    for p,v in contents.items():
        out=target/p
        if out.is_symlink() or (out.exists() and out.read_bytes()!=v):raise ValueError('fixture drift')
        if not out.exists():out.parent.mkdir(parents=True,exist_ok=True);out.write_bytes(v);out.chmod(0o444)
    print(json.dumps({'manifest_sha256':hashlib.sha256(contents['manifest.json']).hexdigest(),
        'operation':'verified_controls_fixture_v1','seed_manifest_sha256':os.environ['SEED_MANIFEST'],'new_git_commit':False}))

if __name__=='__main__':main()
