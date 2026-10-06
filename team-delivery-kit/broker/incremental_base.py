"""Fixed offline operation: derive a unit base from an immutable checkpoint.

No Git, network, commands or credentials. The controller supplies the accepted
snapshot hash and prior operator-owned contract; workers cannot choose these.
"""
import hashlib
import json
import os
from pathlib import Path

from portable_contract import validate, safe_path, is_test_path, MAX_FILE_BYTES


def _bytes(root,name):
    safe_path(name)
    path=Path(root)/name
    if path.is_symlink() or Path(root).is_symlink() or any(p.is_symlink() for p in list(path.parents)[:len(Path(name).parts)-1]) or not path.is_file():
        raise ValueError('regular checkpoint file required')
    data=path.read_bytes()
    if len(data)>MAX_FILE_BYTES:raise ValueError('checkpoint file bound exceeded')
    return data


def derive_contract(previous,new_test):
    previous=validate(previous)
    safe_path(new_test)
    if (new_test in previous['files'] or not new_test.endswith('.py')
            or not Path(new_test).name.startswith('test_')
            or not any(is_test_path(new_test,r,previous['test_command'][0]) for r in previous['test_roots'])):
        raise ValueError('one genuinely new declared test path required')
    contract=json.loads(json.dumps(previous))
    contract['files']=sorted(set(previous['files'])|{new_test})
    contract['test_files']=sorted(set(previous['test_files'])|{new_test})
    contract['protected_files']=sorted(set(previous['protected_files'])|set(previous['test_files']))
    contract['editable_files']=sorted((set(previous['editable_files'])-set(previous['test_files']))|{new_test})
    if contract.get('schema_version')==2:
        contract['required_files']=sorted(set(previous['required_files'])|{new_test})
    return validate(contract)


def materialize(snapshot,target,previous,new_test,checkpoint_sha256,base_sha,*,resume=False):
    snapshot,target=Path(snapshot),Path(target)
    if (target.is_symlink() or snapshot.is_symlink()
            or target.resolve().is_relative_to(snapshot.resolve())
            or snapshot.resolve().is_relative_to(target.resolve())):
        raise ValueError('separate controller snapshot and destination required')
    contract=derive_contract(previous,new_test)
    manifest_bytes=_bytes(snapshot,'manifest.json')
    if hashlib.sha256(manifest_bytes).hexdigest()!=checkpoint_sha256:
        raise ValueError('accepted checkpoint hash mismatch')
    manifest=json.loads(manifest_bytes)
    if set(manifest)!={'files'} or not isinstance(manifest['files'],dict):
        raise ValueError('checkpoint manifest schema required')
    names=set(manifest['files'])
    if names!=set(previous['files']):raise ValueError('complete previous checkpoint inventory required')
    actual={str(p.relative_to(snapshot)) for p in snapshot.rglob('*') if p.is_file() or p.is_symlink()}
    if actual!=names|{'manifest.json'}:raise ValueError('unexpected checkpoint entry')
    contents={}
    for name in names:
        data=_bytes(snapshot,name)
        if manifest['files'][name]!={'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)}:
            raise ValueError('checkpoint bytes changed')
        contents[name]=data
    encoded=json.dumps(contract,sort_keys=True,separators=(',',':')).encode()
    contents['contract.json']=encoded
    hashes={n:hashlib.sha256(data).hexdigest() for n,data in contents.items()}
    if not isinstance(base_sha,str) or len(base_sha)!=40 or any(c not in '0123456789abcdef' for c in base_sha):
        raise ValueError('original Git base identity required')
    base_manifest=json.dumps({'base_sha':base_sha,'files':hashes},sort_keys=True,separators=(',',':')).encode()
    contents['manifest.json']=base_manifest
    existing={str(p.relative_to(target)) for p in target.rglob('*') if p.is_file() or p.is_symlink()}
    if (existing and not resume) or not existing<=set(contents):
        raise ValueError('empty or exact resumable destination required')
    # Validate all existing bytes BEFORE continuing an interrupted copy.
    if any(_bytes(target,n)!=contents[n] for n in existing):
        raise ValueError('partial base drift')
    for name,data in contents.items():
        if name in existing:continue
        destination=target/name
        if target.is_symlink() or any(p.is_symlink() for p in list(destination.parents)[:len(Path(name).parts)-1]):raise ValueError('unsafe destination parent')
        destination.parent.mkdir(parents=True,exist_ok=True)
        with os.fdopen(os.open(destination,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o400),'wb') as f:f.write(data)
    return dict(checkpoint_manifest_sha256=checkpoint_sha256,
        base_manifest_sha256=hashlib.sha256(base_manifest).hexdigest(),
        contract_sha256=hashlib.sha256(encoded).hexdigest(),base_sha=base_sha,
        baseline_test_sha256={n:hashes[n] for n in previous['test_files']},new_test=new_test,
        suite_sha256=hashlib.sha256(json.dumps({'test_image':contract['test_image'],
            'test_command':contract['test_command']},sort_keys=True,separators=(',',':')).encode()).hexdigest())
