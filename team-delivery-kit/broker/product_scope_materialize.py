"""Fixed offline materialization of an independently qualified scope plan.

Copies the ORIGINAL base, not the failed implementation. Only contract.json
changes. Frozen new tests remain separately bound to their historical snapshot;
this operation neither recreates Red nor seeds tests nor grants worker access.
The controller must authenticate native review receipts before launching this
job and again before installing its result. Self-consistency is not authority.
"""
import hashlib
import json
import os
import re
from pathlib import Path
from portable_contract import safe_path,MAX_FILES,MAX_FILE_BYTES
try:
    from . import product_scope_revision as policy
except ImportError:
    import product_scope_revision as policy


def sha(data):return hashlib.sha256(data).hexdigest()


def encoded(value):return json.dumps(value,sort_keys=True,separators=(',',':')).encode()


def safe_file(root,name):
    safe_path(name)
    path=root/name
    if root.is_symlink() or any(p.is_symlink() for p in (path,*path.parents) if p==root or root in p.parents):
        raise ValueError('selected volume cannot contain symlink paths')
    if path.exists() and not path.is_file():raise ValueError('regular artifact file required')
    return path


def qualified_contract(state):
    if (not isinstance(state,dict) or state.get('stage')!='plan_approved'
            or state.get('author_blocked') is not True or state.get('delivery_approval') is not False):
        raise ValueError('approved independent plan with author still blocked required')
    context=state['context'];proposal=state['proposal']
    result=policy.candidate_contract(state['original_contract'],context,proposal)
    qualification=policy.qualify_review(context,proposal,state['review'],state['proposal_task'],
        state['review_task'],state['observed_read_hashes'])
    if (qualification!=state['qualification'] or qualification['status']!='plan_approved'
            or state.get('proposal_sha256')!=policy.digest(proposal)):
        raise ValueError('exact unchanged qualified scope proposal required')
    return result,qualification


def materialize(base,target,state,base_manifest_sha256):
    base,target=Path(base),Path(target)
    contract,qualification=qualified_contract(state)
    if (not isinstance(base_manifest_sha256,str) or not re.fullmatch(r'[a-f0-9]{64}',base_manifest_sha256)
            or base.is_symlink() or target.is_symlink() or not base.is_dir() or not target.is_dir()
            or base.resolve()==target.resolve() or base.resolve() in target.resolve().parents
            or target.resolve() in base.resolve().parents):
        raise ValueError('distinct selected base and destination volumes required')
    manifest_path=safe_file(base,'manifest.json')
    manifest_bytes=manifest_path.read_bytes()
    if sha(manifest_bytes)!=base_manifest_sha256:raise ValueError('original base manifest identity mismatch')
    manifest=json.loads(manifest_bytes)
    if (not isinstance(manifest,dict) or set(manifest)!={'base_sha','files'}
            or not isinstance(manifest['base_sha'],str) or not re.fullmatch(r'[a-f0-9]{40}',manifest['base_sha'])
            or not isinstance(manifest['files'],dict) or not 1<=len(manifest['files'])<=MAX_FILES
            or 'contract.json' not in manifest['files'] or 'manifest.json' in manifest['files']
            or not set(manifest['files'])<=set(contract['files'])|{'contract.json'}):
        raise ValueError('bounded original Git base manifest required')
    contents={}
    for name,digest in manifest['files'].items():
        path=safe_file(base,name)
        if (not isinstance(digest,str) or not re.fullmatch(r'[a-f0-9]{64}',digest)
                or not path.is_file() or path.stat().st_size>MAX_FILE_BYTES):
            raise ValueError('bounded original base file required')
        data=path.read_bytes()
        if sha(data)!=digest:raise ValueError('original baseline hash mismatch')
        contents[name]=data
    if (sum(map(len,contents.values()))>MAX_FILES*MAX_FILE_BYTES
            or json.loads(contents['contract.json'])!=state['original_contract']):
        raise ValueError('original contract or base size mismatch')
    contents['contract.json']=encoded(contract)
    revised=dict(base_sha=manifest['base_sha'],files={name:sha(data) for name,data in contents.items()})
    contents['manifest.json']=encoded(revised)
    pending={str(Path(name).with_name('.'+Path(name).name+'.scope-pending')):name for name in contents}
    if set(pending)&set(contents):raise ValueError('reserved controller staging path collision')
    # Inspect the complete destination before writing any new file. A restart
    # can retain an exact partial copy; conflicts never trigger overwrite/delete.
    for path in target.rglob('*'):
        name=str(path.relative_to(target))
        if path.is_symlink():raise ValueError('destination symlink forbidden')
        if path.is_dir():
            if not any(p.startswith(name+'/') for p in contents):raise ValueError('foreign destination directory')
        elif name in pending and path.is_file():
            if not contents[pending[name]].startswith(path.read_bytes()):
                raise ValueError('interrupted copy differs from qualified revision')
        elif not path.is_file() or name not in contents or path.read_bytes()!=contents[name]:
            raise ValueError('existing destination differs from qualified revision')
    for name in contents:safe_file(target,name)
    for name,data in contents.items():
        path=safe_file(target,name)
        if not path.exists():
            path.parent.mkdir(parents=True,exist_ok=True)
            temporary=safe_file(target,str(Path(name).with_name('.'+Path(name).name+'.scope-pending')))
            partial=temporary.read_bytes() if temporary.exists() else b''
            if not data.startswith(partial):raise ValueError('interrupted copy changed before resume')
            if not temporary.exists() or partial!=data:
                with os.fdopen(os.open(temporary,os.O_WRONLY|os.O_APPEND|os.O_CREAT|os.O_NOFOLLOW,0o600),'ab') as stream:
                    stream.write(data[len(partial):]);stream.flush();os.fsync(stream.fileno())
            if temporary.is_symlink() or temporary.read_bytes()!=data:raise ValueError('pending copy hash mismatch')
            temporary.chmod(0o444)
            # link is atomic and cannot overwrite an existing destination.
            try:os.link(temporary,path,follow_symlinks=False)
            except FileExistsError:
                if path.is_symlink() or path.read_bytes()!=data:raise ValueError('concurrent destination differs')
        if path.is_symlink() or path.read_bytes()!=data:raise ValueError('materialized revision hash mismatch')
        temporary=safe_file(target,str(Path(name).with_name('.'+Path(name).name+'.scope-pending')))
        if temporary.exists():
            if temporary.is_symlink() or temporary.read_bytes()!=data:raise ValueError('pending copy changed before retirement')
            temporary.unlink()  # exact validated controller staging file only
        descriptor=os.open(path.parent,os.O_RDONLY)
        try:os.fsync(descriptor)
        finally:os.close(descriptor)
    return dict(operation='materialized_product_scope_plan_v1',issue_id=qualification['issue_id'],
        source_task=qualification['source_task'],proposal_sha256=qualification['proposal_sha256'],
        review_task=qualification['review_task'],base_sha=manifest['base_sha'],
        original_base_manifest_sha256=base_manifest_sha256,manifest_sha256=sha(contents['manifest.json']),
        original_contract_sha256=state['context']['contract_sha256'],contract_sha256=sha(contents['contract.json']),
        contract=contract,frozen_test_sha256=qualification['frozen_test_sha256'],
        delivery_approval=False,write_grant_issued=False,historical_red_recreated=False)


def main():
    state=json.loads(os.environ['PRODUCT_SCOPE_PLAN_JSON'])
    print(json.dumps(materialize('/base','/revision',state,os.environ['BASE_MANIFEST_SHA256']),
                     sort_keys=True,separators=(',',':')),flush=True)


if __name__=='__main__':main()
