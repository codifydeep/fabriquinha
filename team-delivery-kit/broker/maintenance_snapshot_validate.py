"""Explicit driver maintenance validation; never a product-delivery receipt."""
import ast
import hashlib
import json
from pathlib import Path
import re
import subprocess
from portable_contract import safe_path
try:
    import portable_snapshot_validate as product
except ImportError:
    from broker import portable_snapshot_validate as product

TEST='tests/test_incremental_u3.py'


def preserve_line_window(seed,candidate,start=500,end=553):
    """Frozen source window, not model-declared scope. Preserve C09 and test suffix."""
    lines=seed.splitlines(keepends=True)
    if not 1<start<=end<len(lines):raise ValueError('bounded frozen C10 window required')
    prefix=b''.join(lines[:start-1]);suffix=b''.join(lines[end:])
    if not candidate.startswith(prefix) or not candidate.endswith(suffix):
        raise ValueError('C10 changed verified C09 or protected test suffix')
    return True


def verify_c10_scope(seed,candidate,expected_seed,expected_manifest):
    seed,candidate=map(Path,(seed,candidate))
    _,oldfiles=manifest(seed);raw,_=manifest(candidate)
    if oldfiles[TEST]['sha256']!=expected_seed or hashlib.sha256(raw).hexdigest()!=expected_manifest:
        raise ValueError('exact C09 seed and C10 candidate required')
    return preserve_line_window(product.regular_within(seed,TEST),product.regular_within(candidate,TEST))


def manifest(root):
    raw=product.regular_within(root,'manifest.json')
    files=json.loads(raw)['files']
    for name in files:safe_path(name)
    actual={str(p.relative_to(root)) for p in root.rglob('*') if p.is_file() or p.is_symlink()}
    if actual!=set(files)|{'manifest.json'}:raise ValueError('unexpected maintenance entry')
    for name,item in files.items():
        content=product.regular_within(root,name)
        if item!={'sha256':hashlib.sha256(content).hexdigest(),'bytes':len(content)}:
            raise ValueError('maintenance manifest hash mismatch')
    return raw,files


def verify(base,candidate,previous,expected_manifest,expected_test):
    base,candidate,previous=map(Path,(base,candidate,previous))
    raw,files=manifest(candidate);_,oldfiles=manifest(previous)
    if hashlib.sha256(raw).hexdigest()!=expected_manifest or oldfiles.get(TEST,{}).get('sha256')!=expected_test:
        raise ValueError('maintenance snapshot identity mismatch')
    if set(files)!=set(oldfiles) or any(files[n]!=oldfiles[n] for n in files if n!=TEST):
        raise ValueError('maintenance changed outside assigned test')
    trees=[ast.parse(product.regular_within(root,TEST)) for root in (previous,candidate)]
    body=None
    for tree in trees:
        drivers=[n for n in tree.body if isinstance(n,ast.Assign) and len(n.targets)==1
            and isinstance(n.targets[0],ast.Name) and n.targets[0].id=='DRIVER_BODY']
        if len(drivers)!=1:raise ValueError('one literal driver required')
        body=ast.literal_eval(drivers[0].value)
        if not isinstance(body,str):raise ValueError('string driver required')
        drivers[0].value=ast.Constant(value='DRIVER_ONLY')
    if ast.dump(trees[0],include_attributes=False)!=ast.dump(trees[1],include_attributes=False):
        raise ValueError('maintenance weakened or changed non-driver AST')
    if subprocess.run(['node','--check'],input=body,text=True,capture_output=True,timeout=10).returncode:
        raise ValueError('maintenance driver syntax invalid')
    oldbase,olddelivery=product.BASE,product.DELIVERY
    product.BASE,product.DELIVERY=base,candidate
    try:
        try:product.verify()
        except ValueError as error:
            # All manifest/base/protection checks precede this exact product-only gate.
            if not re.fullmatch(r'new product code required; new test files present=[1-9][0-9]*',str(error)):raise
        else:raise ValueError('maintenance unexpectedly includes product delta')
    finally:product.BASE,product.DELIVERY=oldbase,olddelivery
    spec=product.validate(json.loads(product.regular_within(base,'contract.json')))
    return {**{k:spec[k] for k in ('test_image','test_command','test_success_pattern','test_count_pattern','test_files')},
        'minimum_tests':len(spec['test_files']),'manifest_sha256':expected_manifest,
        'mode':'driver_maintenance_only','baseline_tests_intact':True,'delivery_approval':False}
