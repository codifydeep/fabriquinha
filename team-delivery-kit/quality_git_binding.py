"""Read-only first-submission Git proof for exact immutable delivery bytes.

Repository path and frozen inputs come only from the controller. Does not
create commits, choose a branch, fetch/push, grant a review or approve a merge.
Native source provenance remains the responsibility of persistent capture.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from portable_contract import MAX_FILE_BYTES
from r3_snapshot_probe import probe
try:
    import quality_lifecycle_v2 as quality
    from test_first_protocol import _regular
except ImportError:
    from broker import quality_lifecycle_v2 as quality
    from broker.test_first_protocol import _regular


def require(value):
    if not value:raise ValueError('exact immutable snapshot and Git object binding required')


def git(repo,*args,limit=65536):
    binary=shutil.which('git');require(binary is not None)
    result=subprocess.run([binary,'--no-pager','--no-replace-objects','--literal-pathspecs',
        '-c','core.hooksPath=/dev/null','-c','core.fsmonitor=false','-C',str(repo),*args],
        env=dict(PATH=os.defpath,LC_ALL='C',GIT_CONFIG_NOSYSTEM='1',GIT_CONFIG_GLOBAL='/dev/null',
            GIT_NO_REPLACE_OBJECTS='1',GIT_OPTIONAL_LOCKS='0',GIT_TERMINAL_PROMPT='0'),
        capture_output=True,timeout=15)
    require(result.returncode==0 and len(result.stdout)<=limit)
    return result.stdout


def entry(repo,commit,path):
    rows=git(repo,'ls-tree','-z',commit,'--',path).split(b'\0')
    rows=[r for r in rows if r]
    if not rows:return None
    require(len(rows)==1)
    metadata,name=rows[0].split(b'\t',1)
    mode,kind,blob=metadata.decode('ascii').split(' ')
    require(name.decode('utf-8')==path and kind=='blob' and mode in ('100644','100755')
        and re.fullmatch('[a-f0-9]{40}',blob))
    return dict(mode=mode,blob=blob)


def contents(repo,item):
    size=int(git(repo,'cat-file','-s',item['blob']).strip());require(0<=size<=MAX_FILE_BYTES)
    data=git(repo,'cat-file','blob',item['blob'],limit=MAX_FILE_BYTES)
    require(len(data)==size and hashlib.sha1(b'blob '+str(size).encode()+b'\0'+data).hexdigest()==item['blob'])
    return data


def verify(repo,snapshot,manifest_sha256,plan,commit_sha,frozen_tests):
    quality.validate(plan);quality.sha(commit_sha,40);quality.sha(manifest_sha256)
    repo,snapshot=Path(repo),Path(snapshot)
    require(repo.is_absolute() and repo.is_dir() and repo.resolve()==repo)
    probe(snapshot,manifest_sha256)
    manifest=json.loads(_regular(snapshot,'manifest.json'))['files']
    require(set(manifest)==set(plan['product_files'])|set(plan['protected_files'])
        and isinstance(frozen_tests,dict) and set(frozen_tests)==set(plan['baseline_tests'])|set(plan['new_tests'])
        and all(frozen_tests[p]==sha for p,sha in plan['baseline_tests'].items())
        and all(manifest[p]['sha256']==sha for p,sha in frozen_tests.items()))
    require(git(repo,'rev-parse','--show-object-format').strip()==b'sha1')
    base=plan['base_sha'];require(git(repo,'cat-file','-t',base).strip()==b'commit')
    raw=git(repo,'cat-file','commit',commit_sha)
    require(hashlib.sha1(b'commit '+str(len(raw)).encode()+b'\0'+raw).hexdigest()==commit_sha)
    headers=raw.split(b'\n\n',1)[0].splitlines()
    require([line[7:].decode('ascii') for line in headers if line.startswith(b'parent ')]==[base])
    trees=[line[5:].decode('ascii') for line in headers if line.startswith(b'tree ')]
    require(len(trees)==1 and re.fullmatch('[a-f0-9]{40}',trees[0]))
    changed=git(repo,'diff-tree','--no-ext-diff','--no-renames','--no-commit-id','--name-only','-r','-z',base,commit_sha,'--')
    changed={p.decode('utf-8') for p in changed.split(b'\0') if p}
    require(bool(changed&set(plan['product_files'])) and changed<=set(plan['product_files'])|set(plan['new_tests']))
    identities={}
    for path in sorted(manifest):
        item=entry(repo,commit_sha,path);require(item is not None)
        data=contents(repo,item)
        require(manifest[path]==dict(sha256=hashlib.sha256(data).hexdigest(),bytes=len(data))
            and data==_regular(snapshot,path))
        original=entry(repo,base,path)
        if path in plan['new_tests']:require(original is None)
        elif path in plan['protected_files']:
            require(original is not None and original==item)
        if path in plan['baseline_tests']:
            require(original is not None and hashlib.sha256(contents(repo,original)).hexdigest()==plan['baseline_tests'][path])
        identities[path]=item
    probe(snapshot,manifest_sha256)
    return dict(operation='verified_delivery_commit_v2',plan_sha256=quality.digest(plan),
        manifest_sha256=manifest_sha256,base_sha=base,commit_sha=commit_sha,tree_sha=trees[0],
        changed_paths=sorted(changed),git_files=identities,frozen_tests=frozen_tests,
        execution_authorized=False,merge_authorized=False,delivery_approval=False)
