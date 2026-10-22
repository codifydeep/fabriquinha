"""Controller-owned deterministic local candidate; never push or merge.

Content-addressed object writes are idempotent. A reference gets one persisted
publication intent; uncertain acknowledgement is read back, never reposted.
Inputs must come from the authenticated delivery capture and scoped export,
not from an agent message. No worker or public HTTP endpoint invokes this API.
"""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import time
import uuid
import quality_git_binding as binding

require=binding.require
quality=binding.quality


class Pending(TimeoutError):pass


def canonical(value):
    require(isinstance(value,str) and str(uuid.UUID(value))==value)


def ref_name(plan,task):
    canonical(plan['run_id']);canonical(task)
    return 'refs/delivery-kit/quality/'+plan['run_id']+'/'+task


def write_git(repo,*args,data=None,index=None):
    require(args and args[0] in ('hash-object','read-tree','update-index','write-tree','update-ref'))
    binary=shutil.which('git');require(binary is not None)
    env=binding.environment()
    if index is not None:env['GIT_INDEX_FILE']=str(index)
    result=subprocess.run([binary,'--no-pager','--no-replace-objects','--literal-pathspecs',
        '-c','core.hooksPath=/dev/null','-c','core.fsmonitor=false','-c','core.splitIndex=false',
        '-c','core.sparseCheckout=false','-c','index.sparse=false','-C',str(repo),*args],
        input=data,capture_output=True,env=env,timeout=15)
    require(result.returncode==0 and len(result.stdout)<=65536)
    return result.stdout.strip().decode('ascii')


def observed_ref(repo,ref):
    rows=binding.git(repo,'for-each-ref','--format=%(objectname) %(refname) %(symref)',ref).decode().splitlines()
    matches=[]
    for line in rows:
        oid,name,symbolic=line.split(' ',2)
        if name==ref:
            require(not symbolic)
            matches.append(oid)
    require(len(matches)<=1)
    return matches[0] if matches else None


@contextmanager
def journal(private,request):
    private=Path(private)
    require(private.is_absolute() and private.resolve()==private and private.is_dir()
        and private.stat().st_uid==os.getuid() and not private.stat().st_mode&0o077)
    directory=private/'quality-git-candidates';require(not directory.is_symlink())
    directory.mkdir(mode=0o700,exist_ok=True)
    require(directory.stat().st_uid==os.getuid() and not directory.stat().st_mode&0o077)
    descriptor=os.open(directory/(request+'.lock'),os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    try:
        info=os.fstat(descriptor)
        require(stat.S_ISREG(info.st_mode) and info.st_nlink==1 and info.st_uid==os.getuid() and not info.st_mode&0o077)
        try:fcntl.flock(descriptor,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise Pending('original candidate materialization is active') from None
        yield directory/(request+'.json')
    finally:os.close(descriptor)


def save(path,context,state):
    value=dict(context=context,state=state,context_sha256=quality.digest(context),state_sha256=quality.digest(state))
    descriptor,temporary=tempfile.mkstemp(prefix=path.name+'.',dir=path.parent)
    try:
        with os.fdopen(descriptor,'w') as out:
            json.dump(value,out,sort_keys=True);out.flush();os.fsync(out.fileno())
        os.replace(temporary,path)
        fd=os.open(path.parent,os.O_RDONLY)
        try:os.fsync(fd)
        finally:os.close(fd)
    finally:
        if os.path.exists(temporary):os.unlink(temporary)


def tree(repo,snapshot,plan,directory):
    with tempfile.TemporaryDirectory(prefix='candidate-index-',dir=directory) as scratch:
        index=Path(scratch)/'index'
        write_git(repo,'read-tree',plan['base_sha'],index=index)
        for path in sorted(set(plan['product_files'])|set(plan['new_tests'])):
            data=binding._regular(snapshot,path)
            blob=write_git(repo,'hash-object','-w','--stdin',data=data)
            require(blob==hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest())
            original=binding.entry(repo,plan['base_sha'],path)
            mode=original['mode'] if original else '100644'
            write_git(repo,'update-index','--add','--cacheinfo',mode+','+blob+','+path,index=index)
        result=write_git(repo,'write-tree',index=index);quality.sha(result,40)
        return result


def commit_bytes(context,state):
    timestamp=state['created_at'];require(type(timestamp) is int and timestamp>=0)
    return ('tree '+state['tree_sha']+'\nparent '+context['base_sha']+
        '\nauthor Fabriquinha <agent-'+context['author']+'@delivery-kit.invalid> '+str(timestamp)+' +0000'+
        '\ncommitter Fabriquinha Controller <controller@delivery-kit.invalid> '+str(timestamp)+' +0000\n\n'+
        'quality-v2 '+context['run_id']+' '+context['source_task']+'\nSnapshot: '+context['manifest_sha256']+
        '\nPlan: '+context['plan_sha256']+'\n').encode()


def materialize(repo,snapshot,manifest_sha256,plan,frozen_tests,request,task,private):
    plan=json.loads(json.dumps(plan));frozen_tests=json.loads(json.dumps(frozen_tests))
    for value in (request,task,plan['run_id'],plan['issue_id']):canonical(value)
    quality.validate(plan);quality.sha(manifest_sha256)
    repo,snapshot=Path(repo),Path(snapshot)
    require(repo.is_absolute() and repo.resolve()==repo and repo.is_dir())
    context=dict(operation='local_quality_candidate_v2',repository=str(repo),base_sha=plan['base_sha'],
        manifest_sha256=manifest_sha256,plan_sha256=quality.digest(plan),frozen_sha256=quality.digest(frozen_tests),
        request_id=request,source_task=task,run_id=plan['run_id'],issue_id=plan['issue_id'],author=plan['author'],ref=ref_name(plan,task))
    with journal(private,request) as path:
        require(not path.is_symlink())
        if path.exists():
            info=path.stat()
            require(stat.S_ISREG(info.st_mode) and info.st_nlink==1 and info.st_uid==os.getuid() and not info.st_mode&0o077)
            raw=json.loads(path.read_bytes());state=raw['state']
            require(raw['context']==context and raw['context_sha256']==quality.digest(context)
                and raw['state_sha256']==quality.digest(state)
                and state['stage'] in ('prepared','commit_intent','ref_intent','ready','technical_blocked'))
            if state['stage']=='ready':
                receipt=state['receipt'];proof=receipt['git_proof']
                require(receipt['operation']=='local_quality_candidate_v2' and receipt['stage']=='ready'
                    and receipt['request_id']==request and receipt['source_task']==task and receipt['ref']==context['ref']
                    and receipt['commit_sha']==state['commit_sha'] and observed_ref(repo,context['ref'])==state['commit_sha']
                    and proof['commit_sha']==state['commit_sha'] and proof['base_sha']==context['base_sha']
                    and proof['manifest_sha256']==manifest_sha256 and proof['plan_sha256']==context['plan_sha256']
                    and proof['frozen_tests']==frozen_tests and all(receipt[k] is False and proof[k] is False for k in
                        ('execution_authorized','merge_authorized','delivery_approval')))
                return receipt
            require(state['stage']!='technical_blocked')
        else:
            binding.inputs(repo,snapshot,manifest_sha256,plan,frozen_tests)
            require(observed_ref(repo,context['ref']) is None)  # Never adopt an unregistered reference.
            state=dict(stage='prepared',created_at=int(time.time()),ref_attempted=False,object_write_attempts=0)
            save(path,context,state)
        try:
            binding.inputs(repo,snapshot,manifest_sha256,plan,frozen_tests)
            if state['stage']=='prepared':
                state.update(tree_sha=tree(repo,snapshot,plan,path.parent))
                data=commit_bytes(context,state)
                state.update(stage='commit_intent',commit_sha=hashlib.sha1(b'commit '+str(len(data)).encode()+b'\0'+data).hexdigest())
                save(path,context,state)
            if state['stage']=='commit_intent':
                require(state['object_write_attempts']<2)
                state['object_write_attempts']+=1;save(path,context,state)
                data=commit_bytes(context,state)
                actual=write_git(repo,'hash-object','-t','commit','-w','--stdin',data=data)
                require(actual==state['commit_sha'])
                state.update(stage='ref_intent')
                save(path,context,state)
            if state['stage']=='ref_intent' and not state['ref_attempted']:
                binding.verify(repo,snapshot,manifest_sha256,plan,state['commit_sha'],frozen_tests)
                require(observed_ref(repo,context['ref']) is None)
                state.update(ref_attempted=True,ref_deadline=time.time()+600);save(path,context,state)
                write_git(repo,'update-ref','--no-deref',context['ref'],state['commit_sha'],'0'*40)
            actual=observed_ref(repo,context['ref'])
            if actual is None:
                if time.time()>=state['ref_deadline']:raise ValueError('original reference publication unobserved')
                raise Pending('observe original reference intent; no second update-ref')
            require(actual==state['commit_sha'])
            proof=binding.verify(repo,snapshot,manifest_sha256,plan,state['commit_sha'],frozen_tests)
            receipt=dict(operation='local_quality_candidate_v2',stage='ready',request_id=request,source_task=task,
                ref=context['ref'],commit_sha=actual,git_proof=proof,execution_authorized=False,
                merge_authorized=False,delivery_approval=False)
            state.update(stage='ready',receipt=receipt);save(path,context,state)
            return receipt
        except (TimeoutError,subprocess.TimeoutExpired) as error:
            raise Pending('observe original candidate object/reference; never recreate its identity') from error
        except (ValueError,KeyError,TypeError,OSError) as error:
            state.update(stage='technical_blocked',category=type(error).__name__,automatic_retry=False)
            save(path,context,state)
            raise ValueError('local candidate blocked; inspect preserved journal, never overwrite its ref') from error
