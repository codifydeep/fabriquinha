"""Build a v2 plan from every tracked Git blob, never from mutable worker files.

This operator adapter pins an existing issue and proposed acceptance witnesses.
It does not invent tests/implementation, create a native task or approve a brief.
The first native adapter supports full Python discovery and frozen Node baseline.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
from broker import quality_lifecycle_enrollment as enrollment
from portable_contract import is_test_path
from quality_candidate_service import write_once
from quality_git_candidate import require
from migrate_quality_candidate_pin import folder,read

FIELDS={'run_id','issue_id','author','reviewer','criteria','new_tests','product_files',
    'criterion_tests','qa_cases','test_image'}


def build(repository,base_sha,blobs,selection,maintenance_operation):
    require(isinstance(selection,dict) and set(selection)==FIELDS and isinstance(blobs,dict)
        and all(isinstance(p,str) and isinstance(raw,bytes) for p,raw in blobs.items()))
    json.dumps(selection,allow_nan=False)
    for key in ('run_id','issue_id','author','reviewer'):enrollment.canonical(selection[key])
    enrollment.canonical(maintenance_operation)
    require(set(selection['product_files'])<=set(blobs) and not set(selection['new_tests'])&set(blobs))
    files=sorted(set(blobs)|set(selection['new_tests']))
    baseline={p:hashlib.sha256(raw).hexdigest() for p,raw in blobs.items() if is_test_path(p,'.','python3')}
    editable=sorted(selection['product_files']+selection['new_tests'])
    contract=dict(schema_version=2,repository=repository,base_branch='main',files=files,
        protected_files=sorted(set(blobs)-set(selection['product_files'])),editable_files=editable,
        required_files=files,test_files=sorted(set(baseline)|set(selection['new_tests'])),
        test_roots=['.'],test_command=['python3','-m','unittest','discover','-s','.','-q'],
        test_image=selection['test_image'],test_success_pattern=r'Ran [1-9][0-9]* tests? in [^\n]+\n\nOK',
        test_count_pattern=r'Ran ([0-9]+) tests? in ',qa_cases=selection['qa_cases'])
    plan={k:selection[k] for k in ('run_id','issue_id','author','reviewer','criteria','new_tests','product_files','criterion_tests')}
    plan.update(version=2,policy=enrollment.policy.POLICY,base_sha=base_sha,
        contract_sha256=enrollment.policy.digest(contract),baseline_tests=baseline,
        protected_files=sorted(set(files)-set(selection['product_files'])))
    node=enrollment.policy.node.paths(files)
    if node:plan['node_baseline_tests']={p:hashlib.sha256(blobs[p]).hexdigest() for p in sorted(node)}
    payload=dict(plan=plan,contract=contract,maintenance_operation=maintenance_operation)
    enrollment.request(payload);return payload


def git_blobs(checkout,repository):
    root=Path(checkout);require(root.is_absolute() and root.resolve()==root and root.is_dir())
    def git(*args):return subprocess.check_output(['git','-C',str(root),*args],timeout=30)
    origin=git('remote','get-url','origin').decode().strip()
    require(origin in ('https://github.com/'+repository+'.git','git@github.com:'+repository+'.git'))
    sha=git('rev-parse','HEAD').decode().strip();require(re.fullmatch('[a-f0-9]{40}',sha))
    require(git('rev-parse','origin/main').decode().strip()==sha)
    remote=subprocess.check_output(['gh','api','repos/'+repository+'/git/ref/heads/main','--jq','.object.sha'],text=True,timeout=30).strip()
    require(remote==sha)
    checks=json.loads(subprocess.check_output(['gh','api','repos/'+repository+'/commits/'+sha+'/check-runs'],text=True,timeout=30))
    require(any(c.get('name')=='ci' and c.get('conclusion')=='success' for c in checks['check_runs']))
    rows=git('ls-tree','-rz','--full-tree',sha).split(b'\0');blobs={}
    for row in rows:
        if not row:continue
        metadata,path=row.split(b'\t',1);mode,kind,oid=metadata.decode().split()
        require(mode in ('100644','100755') and kind=='blob')
        name=path.decode();enrollment.policy.safe_path(name)
        raw=git('cat-file','blob',oid.decode() if isinstance(oid,bytes) else oid)
        require(len(raw)<=32768);blobs[name]=raw
    require(0<len(blobs)<128);return sha,blobs


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('repository','checkout','selection','selection-pin','maintenance-operation','output'):parser.add_argument('--'+key,required=True)
    args=parser.parse_args();raw=read(Path(args.selection))
    require(hashlib.sha256(raw).hexdigest()==args.selection_pin)
    def pairs(values):
        require(len({k for k,_ in values})==len(values));return dict(values)
    def invalid(_):raise ValueError('finite JSON required')
    selection=json.loads(raw,object_pairs_hook=pairs,parse_constant=invalid)
    sha,blobs=git_blobs(args.checkout,args.repository)
    payload=build(args.repository,sha,blobs,selection,args.maintenance_operation)
    output=Path(args.output);folder(output.parent)
    encoded=json.dumps(payload,sort_keys=True).encode();write_once(output,encoded)
    contract_path=output.with_suffix('.contract.json')
    write_once(contract_path,json.dumps(payload['contract'],sort_keys=True).encode())
    print(json.dumps(dict(stage='prepared_not_enrolled',payload=str(output),pin=hashlib.sha256(encoded).hexdigest(),
        contract=str(contract_path),
        files=len(payload['contract']['files']),python_baseline_files=len(payload['plan']['baseline_tests']),
        node_baseline_files=len(payload['plan'].get('node_baseline_tests',{})),model_calls=0,delivery_approval=False)))
