"""One durable same-SHA PR event recovery, never CI or merge approval."""
import fcntl
import json
from pathlib import Path
import re
import subprocess


def github(path, method='GET', state=None):
    cmd=['gh','api',path,'-X',method]
    if state is not None:cmd+=['-f','state='+state]
    return json.loads(subprocess.check_output(cmd,text=True,timeout=15))


def recover(private,repository,number,head,base,*,api=github,save=None):
    from release_eval import save_receipt
    save=save or save_receipt
    if (not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repository)
            or type(number) is not int or number<1
            or any(not re.fullmatch(r'[0-9a-f]{40}',s) for s in (head,base))):
        raise ValueError('invalid CI recovery identity')
    folder=Path(private)/'missing-ci-recovery'
    if not folder.is_absolute() or any(p.is_symlink() for p in (folder,*folder.parents)):
        raise ValueError('unsafe CI recovery storage')
    folder.mkdir(mode=0o700,exist_ok=True)
    path=folder/(str(number)+'-'+head+'.json');lock=folder/(str(number)+'-'+head+'.lock')
    if any(p.is_symlink() for p in (folder,*folder.parents,path,lock)):
        raise ValueError('unsafe CI recovery storage')
    identity=dict(repository=repository,number=number,head=head,base=base)
    endpoint='repos/'+repository+'/pulls/'+str(number)
    def observe():
        pr=api(endpoint)
        if (pr['head']['sha']!=head or pr['base']['sha']!=base
                or pr['base']['ref']!='main' or not pr['head']['ref'].startswith('codex/')
                or pr['head']['repo']['full_name']!=repository or pr['base']['repo']['full_name']!=repository
                or pr.get('draft') or pr.get('merged')):
            raise ValueError('CI recovery PR identity drift')
        return pr['state']
    with lock.open('a+') as stream:
        fcntl.flock(stream.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        record=json.loads(path.read_text()) if path.exists() else dict(identity=identity,phase='new',ci_approval=False)
        if record.get('identity')!=identity or record.get('ci_approval') is not False:
            raise ValueError('CI recovery receipt drift')
        state=observe();phase=record['phase']
        def persist(value):record['phase']=value;save(path,record)
        if phase=='reopened':return False
        if phase=='reopen_intent':
            if state!='open':raise ValueError('CI reopen outcome uncertain; no repeat')
            persist('reopened');return False
        if phase=='close_intent':
            if state!='closed':raise ValueError('CI close outcome uncertain; no repeat')
            persist('closed');phase='closed'
        if phase=='new':
            if state!='open':raise ValueError('CI recovery requires open PR')
            suites=api('repos/'+repository+'/commits/'+head+'/check-suites')
            runs=api('repos/'+repository+'/actions/runs?head_sha='+head)
            workflow=api('repos/'+repository+'/actions/workflows/ci.yml')
            if (suites.get('total_count')!=0 or runs.get('total_count')!=0
                    or workflow.get('state')!='active' or workflow.get('path')!='.github/workflows/ci.yml'):
                return False
            # Persist BEFORE each external write. A failed acknowledgement is
            # observed on restart, never blindly replayed.
            persist('close_intent');api(endpoint,'PATCH','closed')
            if observe()!='closed':raise ValueError('CI close outcome uncertain; no repeat')
            persist('closed');state='closed';phase='closed'
        if phase!='closed' or state!='closed':raise ValueError('invalid CI recovery phase')
        persist('reopen_intent');api(endpoint,'PATCH','open')
        if observe()!='open':raise ValueError('CI reopen outcome uncertain; no repeat')
        persist('reopened');return True
