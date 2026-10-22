"""Fixed post-implementation copier; freezes bytes, never declares Green.

The controller must authenticate the completed native author, stopped worker,
closed lease and independent freeze before invoking this socketless helper.
Only declared product bytes may differ from the reviewed Red snapshot.
"""
import hashlib
import json
import os
from pathlib import Path
from quality_red_observation import inputs,require
from r3_snapshot_probe import probe
try:
    from test_first_protocol import _regular
    import quality_lifecycle_v2 as quality
except ImportError:
    from broker.test_first_protocol import _regular
    from broker import quality_lifecycle_v2 as quality

MAX_TOTAL_BYTES=16*1024*1024


def inventory(root,allowed):
    names=set()
    for p in root.rglob('*'):
        name=p.relative_to(root).as_posix()
        require(not p.is_symlink(),'snapshot_symlink')
        if p.is_dir():require(any(n.startswith(name+'/') for n in allowed),'snapshot_undeclared_directory')
        else:
            require(p.is_file() and name in allowed,'snapshot_undeclared_file')
            names.add(name)
    return names


def write_once(path,data):
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    with os.fdopen(os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o400),'wb') as out:
        out.write(data);out.flush();os.fsync(out.fileno())
    descriptor=os.open(path.parent,os.O_RDONLY)
    try:os.fsync(descriptor)
    finally:os.close(descriptor)


def copy(base,reviewed,workspace,destination,plan,base_manifest,reviewed_manifest,frozen_tests,*,resume=False):
    require(type(resume) is bool,'snapshot_resume_invalid')
    base,reviewed,workspace,destination=map(Path,(base,reviewed,workspace,destination))
    require(all(p.is_dir() and not p.is_symlink() for p in (base,reviewed,workspace,destination)),
        'snapshot_root_invalid')
    spec,tests,_=inputs(base,reviewed,plan,base_manifest,reviewed_manifest)
    require(tests==frozen_tests,'snapshot_freeze_mismatch')
    require(set(plan['product_files'])==set(spec['editable_files'])-set(plan['new_tests']),
        'snapshot_product_partition_mismatch')
    names=set(spec['files']);marker='.delivery-kit-base.json'
    require(inventory(workspace,names|{marker})==names|{marker},'snapshot_source_inventory_mismatch')
    require(json.loads(_regular(workspace,marker))==dict(base_sha=plan['base_sha'],manifest_sha256=base_manifest),
        'snapshot_base_marker_mismatch')
    contents={p:_regular(workspace,p) for p in sorted(names)}
    require(sum(map(len,contents.values()))<=MAX_TOTAL_BYTES,'snapshot_total_size_exceeded')
    for path,data in contents.items():
        if path not in plan['product_files']:
            require(data==_regular(reviewed,path),'snapshot_protected_bytes_changed')
    facts={p:dict(sha256=hashlib.sha256(data).hexdigest(),bytes=len(data)) for p,data in contents.items()}
    require({p:facts[p]['sha256'] for p in tests}==frozen_tests,'snapshot_frozen_tests_changed')
    manifest=json.dumps(dict(files=facts),sort_keys=True,separators=(',',':')).encode()
    actual=inventory(destination,names|{'manifest.json'})
    require(not actual or resume,'snapshot_destination_not_empty')
    if 'manifest.json' in actual:
        require(actual==names|{'manifest.json'},'snapshot_completed_inventory_changed')
    outputs={**contents,'manifest.json':manifest}
    # Check the entire partial destination before writing any additional file.
    for path in actual:require(_regular(destination,path)==outputs[path],'snapshot_resume_bytes_changed')
    for path,data in outputs.items():
        if path not in actual:write_once(destination/path,data)
    require(inventory(workspace,names|{marker})==names|{marker}
        and all(_regular(workspace,p)==data for p,data in contents.items()),'snapshot_source_changed_during_copy')
    inputs(base,reviewed,plan,base_manifest,reviewed_manifest)
    manifest_sha=hashlib.sha256(manifest).hexdigest();probe(destination,manifest_sha)
    return dict(operation='post_implementation_snapshot_v2',plan_sha256=quality.digest(plan),
        base_sha=plan['base_sha'],base_manifest_sha256=base_manifest,reviewed_manifest_sha256=reviewed_manifest,
        manifest_sha256=manifest_sha,file_inventory=facts,tests=frozen_tests,
        execution_authorized=False,delivery_approval=False)
