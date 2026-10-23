"""Pinned one-shot host service; launchd schedules it, journals own recovery.

No worker/model calls or delivery approval. Two interrupted/unexpected ticks
latch a CTO hold; mere process reappearance cannot clear it. Status is local
read-only and never probes Docker or restarts a pending operation.
"""
import argparse
import json
import os
from pathlib import Path
import plistlib
import re
import stat
import sys
import time
import uuid
import quality_candidate_dispatch as dispatch
from quality_git_candidate import journal,save,quality,require,Pending

ROOT=Path(__file__).resolve().parent


def config(path,pin):
    require(isinstance(pin,str) and re.fullmatch('[a-f0-9]{64}',pin))
    value=dispatch.configuration(path,pin=pin)
    authority=dispatch.Authority(value['namespace'],value['image'])
    dispatch.context(authority,value['repositories'])
    return value,authority,dict(operation='quality_candidate_host_service_v2',
        config=str(Path(path)),config_sha256=pin,namespace=value['namespace'])


def token(namespace):return str(uuid.uuid5(uuid.NAMESPACE_URL,'quality-candidate-service:'+namespace))


def load(path,identity):
    require(not path.is_symlink())
    if not path.exists():return None
    info=path.stat();require(stat.S_ISREG(info.st_mode) and info.st_uid==os.getuid()
        and info.st_nlink==1 and not info.st_mode&0o077 and info.st_size<=1048576)
    value=json.loads(path.read_bytes());state=value['state']
    require(value['context']==identity and value['context_sha256']==quality.digest(identity)
        and value['state_sha256']==quality.digest(state) and state['delivery_approval'] is False
        and type(state['unexpected_exits']) is int and 0<=state['unexpected_exits']<=2
        and state['stage'] in ('tick_intent','observed','unexpected_exit','crash_escalation'))
    return state


def run_once(path,pin):
    value,authority,identity=config(path,pin)
    with journal(value['private'],token(value['namespace']),family='quality-candidate-dispatch') as receipt:
        previous=load(receipt,identity)
        if previous and previous['stage']=='crash_escalation':return previous
        failures=previous['unexpected_exits'] if previous else 0
        if previous and previous['stage']=='tick_intent':failures+=1
        state=dict(stage='tick_intent',unexpected_exits=failures,started_at=time.time(),
            owner='techlead',delivery_approval=False,model_calls=0)
        if failures>=2:
            state.update(stage='crash_escalation',owner='cto',automatic_retry=False,
                next_action='diagnose preserved service and child journals; no reset by service restart')
            save(receipt,identity,state);return state
        save(receipt,identity,state)
        try:
            result=dispatch.tick(authority,value['repositories'],value['private'])
        except Pending:
            # Another authoritative tick owns the lock. No child or PID is
            # declared dead, no operation is replayed, no crash budget reset.
            result=dict(stage='busy_or_pending',delivery_approval=False,model_calls=0)
        except Exception as error:
            state.update(stage='unexpected_exit',unexpected_exits=failures+1,
                category=type(error).__name__,owner='cto',automatic_retry=False,
                next_action='inspect private journals; no worker replacement')
            if state['unexpected_exits']>=2:state['stage']='crash_escalation'
            save(receipt,identity,state);return state
        state.update(stage='observed',finished_at=time.time(),result=result,
            unexpected_exits=failures if result['stage']=='busy_or_pending' else 0)
        save(receipt,identity,state);return state


def status(path,pin):
    value,authority,identity=config(path,pin)
    private=Path(value['private'])
    queue=dispatch.status(authority,value['repositories'],private)
    receipt=private/'quality-candidate-dispatch'/(token(value['namespace'])+'.json')
    return dict(stage='available',service=load(receipt,identity),queue=queue,
        delivery_approval=False,model_calls=0)


def write_once(path,data):
    require(not path.is_symlink())
    if path.exists():
        info=path.stat();require(stat.S_ISREG(info.st_mode) and info.st_uid==os.getuid()
            and info.st_nlink==1 and not info.st_mode&0o077 and path.read_bytes()==data)
        return
    fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'wb') as out:out.write(data);out.flush();os.fsync(out.fileno())
    fd=os.open(path.parent,os.O_RDONLY)
    try:os.fsync(fd)
    finally:os.close(fd)


def register(path,pin,*,native_paths=False,persist_login=False):
    require(not persist_login or (native_paths and sys.platform=='darwin'))
    value,_,_=config(path,pin)
    # Validate the configured checkout origin before installing a scheduler.
    from quality_delivery_candidate import repository
    for name,checkout in value['repositories'].items():repository(checkout,name)
    private=Path(value['private']);require(private.is_absolute() and private.resolve()==private
        and private.is_dir() and private.stat().st_uid==os.getuid() and not private.stat().st_mode&0o077)
    directory=private/'host-service';require(not directory.is_symlink())
    directory.mkdir(mode=0o700,exist_ok=True)
    require(directory.stat().st_uid==os.getuid() and not directory.stat().st_mode&0o077)
    label='com.codifydeep.delivery-kit.'+value['namespace'].removeprefix('delivery-kit-')+'.quality-candidates'
    logdir=directory
    if native_paths:
        require(sys.platform=='darwin')
        logdir=Path.home()/'Library'/'Logs'/'DeliveryKit'/value['namespace']
        require(not any(p.is_symlink() for p in (logdir,*logdir.parents)))
        logdir.mkdir(mode=0o700,parents=True,exist_ok=True)
        require(logdir.stat().st_uid==os.getuid() and not logdir.stat().st_mode&0o077)
    log=logdir/(label+'.log');require(not log.is_symlink())
    if not log.exists():write_once(log,b'')
    info=log.stat();require(stat.S_ISREG(info.st_mode) and info.st_uid==os.getuid()
        and info.st_nlink==1 and not info.st_mode&0o077)
    plist=dict(Label=label,ProgramArguments=[sys.executable,'-u',str(ROOT/'quality_candidate_service.py'),
        '--config',str(Path(path)),'--pin',pin],WorkingDirectory=str(Path.home()),
        EnvironmentVariables={'PATH':'/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin'},
        RunAtLoad=True,StartInterval=15,ThrottleInterval=15,
        StandardOutPath=str(log),StandardErrorPath=str(log))
    generation=quality.digest(dict(config=str(Path(path)),pin=pin))[:24]
    target=directory/(label+'.'+generation+('.native.plist' if native_paths else '.plist'))
    write_once(target,plistlib.dumps(plist,sort_keys=True))
    login=None
    if persist_login:
        folder=Path.home()/'Library'/'LaunchAgents'
        require(not any(p.is_symlink() for p in (folder,*folder.parents)))
        folder.mkdir(mode=0o700,parents=True,exist_ok=True)
        require(folder.stat().st_uid==os.getuid() and not folder.stat().st_mode&0o022)
        login=folder/(label+'.plist');write_once(login,target.read_bytes())
    return dict(stage='registered_not_started',label=label,plist=str(target),config_sha256=pin,
        login_plist=str(login) if login else None,delivery_approval=False,model_calls=0)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',required=True);parser.add_argument('--pin',required=True)
    modes=parser.add_mutually_exclusive_group();modes.add_argument('--status',action='store_true')
    modes.add_argument('--register',action='store_true')
    parser.add_argument('--persist-login',action='store_true');args=parser.parse_args()
    require(not args.persist_login or args.register)
    try:
        result=(register(args.config,args.pin,native_paths=sys.platform=='darwin',persist_login=args.persist_login) if args.register
            else (status if args.status else run_once)(args.config,args.pin))
    except Pending:result=dict(stage='busy_or_pending',delivery_approval=False,model_calls=0)
    except (ValueError,KeyError,TypeError,OSError):
        result=dict(stage='configuration_blocked',owner='cto',automatic_retry=False,
            next_action='check registration and preserved journals; do not reset private state',delivery_approval=False,model_calls=0)
    print(json.dumps(result,sort_keys=True),flush=True)


if __name__=='__main__':main()
