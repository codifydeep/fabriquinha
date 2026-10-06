"""Preservation proof for an interrupted implementation, never delivery proof."""
import hashlib
import json
import os
from pathlib import Path
from portable_contract import validate
try:from portable_snapshot_validate import regular_within
except ImportError:from broker.portable_snapshot_validate import regular_within


def inspect(base,snapshot,red_hashes):
    base,snapshot=Path(base),Path(snapshot)
    contract=validate(json.loads(regular_within(base,'contract.json')))
    original=json.loads(regular_within(base,'manifest.json'))
    raw=regular_within(snapshot,'manifest.json');manifest=json.loads(raw)
    if set(manifest)!={'files'}:raise ValueError('recovery manifest schema changed')
    names=set(manifest['files'])
    required=(set(original['files'])-{'contract.json'})|set(red_hashes)
    if not required<=names or not names<=set(contract['files']):raise ValueError('recovery snapshot declared file scope changed')
    actual={str(p.relative_to(snapshot)) for p in snapshot.rglob('*') if p.is_file() or p.is_symlink()}
    if actual!=set(names)|{'manifest.json'}:raise ValueError('recovery snapshot layout changed')
    changed=[]
    for name in names:
        content=regular_within(snapshot,name);sha=hashlib.sha256(content).hexdigest()
        if manifest['files'][name]!={'sha256':sha,'bytes':len(content)}:raise ValueError('recovery snapshot hash changed')
        if name in original['files']:
            before=regular_within(base,name)
            if hashlib.sha256(before).hexdigest()!=original['files'][name]:raise ValueError('recovery base changed')
            if content!=before:
                if name not in contract['editable_files'] or name in contract['protected_files'] or name in contract['test_files']:
                    raise ValueError('protected file changed before recovery')
                changed.append(name)
    new_tests=set(contract['test_files'])-set(original['files'])
    if set(red_hashes)!=new_tests or any(manifest['files'][n]['sha256']!=red_hashes[n] for n in new_tests):
        raise ValueError('frozen Red test changed before recovery')
    return dict(manifest_sha256=hashlib.sha256(raw).hexdigest(),files=len(names),
        frozen_tests_unchanged=True,changed_code_count=len(changed),delivery_approval=False,
        provenance='controller_recovery_snapshot_preservation_v1')


def copy_for_recovery(base,workspace,snapshot,red_hashes):
    """Preserve present approved files; unfinished future product files may be absent."""
    base,workspace,snapshot=Path(base),Path(workspace),Path(snapshot)
    contract=validate(json.loads(regular_within(base,'contract.json')))
    original=json.loads(regular_within(base,'manifest.json'))
    actual={str(p.relative_to(workspace)) for p in workspace.rglob('*') if p.is_file() or p.is_symlink()}
    marker='.delivery-kit-base.json';required=(set(original['files'])-{'contract.json'})|set(red_hashes)
    if not required<=actual or not actual<=set(contract['files'])|{marker}:raise ValueError('recovery workspace declared scope changed')
    if marker in actual:
        expected=dict(base_sha=original['base_sha'],manifest_sha256=hashlib.sha256(regular_within(base,'manifest.json')).hexdigest())
        if json.loads(regular_within(workspace,marker))!=expected:raise ValueError('recovery workspace base marker changed')
    if any(snapshot.iterdir()):raise ValueError('fresh recovery snapshot required')
    files={}
    for name in sorted(actual-{marker}):
        content=regular_within(workspace,name);target=snapshot/name;target.parent.mkdir(parents=True,exist_ok=True)
        with os.fdopen(os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o400),'wb') as stream:stream.write(content)
        files[name]=dict(sha256=hashlib.sha256(content).hexdigest(),bytes=len(content))
    with os.fdopen(os.open(snapshot/'manifest.json',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o400),'w') as stream:
        json.dump(dict(files=files),stream,sort_keys=True,separators=(',',':'))
    return inspect(base,snapshot,red_hashes)
