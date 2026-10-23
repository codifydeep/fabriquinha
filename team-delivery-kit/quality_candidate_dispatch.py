"""Persistent fair host dispatcher for controller-owned local Git candidates.

No model calls, native wakeups, pushes, merges or delivery approvals. A kernel
flock serializes ticks; files/PIDs alone never imply a live or dead worker.
Ticket ordering survives restarts and cannot be monopolized by a pending card.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import sqlite3
import stat
import time
import uuid
from quality_git_candidate import journal,quality,require,canonical,Pending
from quality_candidate_authority import Authority
from quality_delivery_candidate import advance_remote


def context(authority,repositories):
    require(isinstance(repositories,dict) and bool(repositories) and len(repositories)<=128)
    for name,path in repositories.items():
        require(isinstance(name,str) and re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',name)
            and all(part not in ('.','..') for part in name.split('/')) and isinstance(path,str))
        p=Path(path);require(p.is_absolute() and p.resolve()==p and p.is_dir())
    return dict(namespace=authority.namespace,image=authority.image,repositories=repositories)


def state(con,request):
    row=con.execute('SELECT state,sha256 FROM tasks WHERE request_id=?',(request,)).fetchone()
    if not row:return None
    value=json.loads(row[0]);require(quality.digest(value)==row[1] and value['request_id']==request
        and value['stage'] in ('ready','pending','bound','technical_blocked') and value['delivery_approval'] is False)
    return value


def store(con,value,ticket):
    con.execute('INSERT INTO tasks VALUES(?,?,?,?) ON CONFLICT(request_id) DO UPDATE SET '
        'state=excluded.state,sha256=excluded.sha256,ticket=excluded.ticket',
        (value['request_id'],json.dumps(value,sort_keys=True),quality.digest(value),ticket))


def next_ticket(con):
    con.execute('UPDATE meta SET ticket=ticket+1 WHERE id=1')
    return con.execute('SELECT ticket FROM meta WHERE id=1').fetchone()[0]


def tick(authority,repositories,private,*,limit=2,effects=None):
    require(type(limit) is int and 1<=limit<=2)
    identity=context(authority,repositories);token=str(uuid.uuid5(uuid.NAMESPACE_URL,'quality-candidate-dispatch:'+authority.namespace))
    with journal(private,token,family='quality-candidate-dispatch') as lockpath:
        path=lockpath.with_suffix('.sqlite');require(not path.is_symlink())
        if not path.exists():
            descriptor=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(descriptor)
        info=path.stat();require(stat.S_ISREG(info.st_mode) and info.st_uid==os.getuid() and info.st_nlink==1 and not info.st_mode&0o077)
        con=sqlite3.connect(path,timeout=5)
        try:
            with con:
                con.execute('CREATE TABLE IF NOT EXISTS meta(id INTEGER PRIMARY KEY,context TEXT,sha256 TEXT,cursor INTEGER,ticket INTEGER,health TEXT)')
                con.execute('CREATE TABLE IF NOT EXISTS tasks(request_id TEXT PRIMARY KEY,state TEXT,sha256 TEXT,ticket INTEGER)')
                row=con.execute('SELECT context,sha256,cursor FROM meta WHERE id=1').fetchone()
                if row:require(json.loads(row[0])==identity and row[1]==quality.digest(identity));cursor=row[2]
                else:
                    con.execute('INSERT INTO meta VALUES(1,?,?,0,0,NULL)',(json.dumps(identity,sort_keys=True),quality.digest(identity)));cursor=0
            def finish(value):
                value={**value,'delivery_approval':False,'model_calls':0}
                with con:con.execute('UPDATE meta SET health=? WHERE id=1',(json.dumps(value,sort_keys=True),))
                return value
            def unavailable(category,owner='techlead'):
                previous=con.execute('SELECT health FROM meta WHERE id=1').fetchone()[0]
                previous=json.loads(previous) if previous else {}
                since=previous.get('unavailable_since',time.time())
                elapsed=max(0,time.time()-since)
                return finish(dict(stage='technical_blocked' if elapsed>=1800 or owner=='cto' else 'control_plane_pending',
                    owner=owner,category=category,unavailable_since=since,alert_due=elapsed>=600,
                    automatic_retry=False,observed=[],next_action='read-only authority probe; preserve all effect journals'))
            try:about=authority.about()
            except (Pending,TimeoutError,OSError):return unavailable('controller_observation_unavailable')
            except (ValueError,KeyError,TypeError):return unavailable('controller_identity_or_response_rejected','cto')
            if about['maintenance']:return finish(dict(stage='maintenance',observed=[]))
            if not about['v2_enabled'] or not about['implementation_enabled']:return finish(dict(stage='disabled',observed=[]))
            if about.get('queue_supported') is not True:
                return finish(dict(stage='configuration_blocked',owner='cto',category='controller_queue_adapter_missing',observed=[]))
            try:
                page=authority.pending(cursor)
                require(page['stage']=='queued' and isinstance(page['requests'],list) and len(page['requests'])<=128
                    and all(isinstance(v,str) for v in page['requests'])
                    and len(set(page['requests']))==len(page['requests']) and type(page['next_after']) is int
                    and 0<=page['next_after']<2**63 and isinstance(page['rejected_rowids'],list)
                    and len(page['rejected_rowids'])<=128
                    and all(type(v) is int and v>0 for v in page['rejected_rowids']))
                for request in page['requests']:canonical(request)
            except (Pending,TimeoutError,OSError):return unavailable('controller_queue_unavailable')
            except (ValueError,KeyError,TypeError):return unavailable('controller_queue_rejected','cto')
            now=time.time()
            with con:
                for request in page['requests']:
                    canonical(request)
                    if con.execute('SELECT 1 FROM tasks WHERE request_id=?',(request,)).fetchone() is None:store(con,dict(request_id=request,stage='ready',started_at=now,
                        deadline=now+1800,observations=0,owner='techlead',alert_due=False,delivery_approval=False),next_ticket(con))
                con.execute('UPDATE meta SET cursor=? WHERE id=1',(page['next_after'],))
            rows=con.execute('SELECT request_id FROM tasks ORDER BY ticket,request_id').fetchall();selected=[];rejected=[]
            for (request,) in rows:
                try:value=state(con,request)
                except (ValueError,KeyError,TypeError):rejected.append(request);continue
                if value['stage'] not in ('bound','technical_blocked'):selected.append(request)
                if len(selected)==limit:break
            observed=[]
            for request in selected:
                value=state(con,request)
                with con:
                    value.update(observations=value['observations']+1,alert_due=time.time()>=value['started_at']+600)
                    ticket=next_ticket(con);store(con,value,ticket)
                try:
                    # Inspect before selecting a checkout; that identity comes
                    # from the controller's enrolled repository, never a model.
                    item=authority.inspect(request)
                    packet=item['identity']['packet'] if item['stage']=='bound' else item['packet']
                    repo=repositories.get(packet['repository'])
                    require(repo is not None)
                    if time.time()>=value['deadline'] and item['stage']!='bound':
                        value.update(stage='technical_blocked',owner='techlead',
                            category='candidate_observation_deadline',automatic_retry=False,
                            next_action='diagnose preserved journals; no new export or Git effects')
                    else:
                        receipt=advance_remote(authority,request,repo,private,effects=effects)
                        value.update(stage='bound',receipt_sha256=quality.digest(receipt),next_action='controller observe exact binding for Green')
                except Pending:
                    value.update(stage='pending',next_action='observe original export/Git/binding journals; no replacement execution')
                    if time.time()>=value['deadline']:value.update(stage='technical_blocked',owner='techlead',
                        category='candidate_observation_deadline',automatic_retry=False)
                except (TimeoutError,OSError):
                    value.update(stage='pending',category='control_plane_unavailable')
                    if time.time()>=value['deadline']:value.update(stage='technical_blocked',owner='techlead',automatic_retry=False)
                except (ValueError,KeyError,TypeError):
                    value.update(stage='technical_blocked',owner='cto',category='candidate_authority_or_configuration_rejected',automatic_retry=False)
                with con:store(con,value,ticket)
                observed.append(value)
            return finish(dict(stage='observed',observed=observed,source_rejected_rowids=page['rejected_rowids'],
                local_integrity_rejections=rejected))
        finally:con.close()


def configuration(path,*,pin=None):
    path=Path(path);require(path.is_absolute() and path.resolve()==path and path.is_file())
    info=path.stat();require(info.st_uid==os.getuid() and info.st_nlink==1 and not info.st_mode&0o077
        and 0<info.st_size<=65536)
    def unique(pairs):
        require(len({key for key,_ in pairs})==len(pairs));return dict(pairs)
    def invalid(_):raise ValueError('nonfinite dispatcher configuration')
    raw=path.read_bytes()
    if pin is not None:require(isinstance(pin,str) and re.fullmatch('[a-f0-9]{64}',pin)
        and hashlib.sha256(raw).hexdigest()==pin)
    value=json.loads(raw,object_pairs_hook=unique,parse_constant=invalid)
    require(isinstance(value,dict) and set(value)=={'namespace','image','private','repositories'})
    return value


def status(authority,repositories,private):
    """Read existing queue only: no Docker probes, migrations, locks or effects."""
    identity=context(authority,repositories);private=Path(private)
    require(private.is_absolute() and private.resolve()==private and private.is_dir()
        and private.stat().st_uid==os.getuid() and not private.stat().st_mode&0o077)
    token=str(uuid.uuid5(uuid.NAMESPACE_URL,'quality-candidate-dispatch:'+authority.namespace))
    directory=private/'quality-candidate-dispatch';require(not directory.is_symlink())
    path=directory/(token+'.sqlite');require(not path.is_symlink())
    if not path.exists():return dict(stage='unobserved',tasks=[],delivery_approval=False)
    info=path.stat();require(stat.S_ISREG(info.st_mode) and info.st_uid==os.getuid() and info.st_nlink==1
        and not info.st_mode&0o077 and directory.stat().st_uid==os.getuid() and not directory.stat().st_mode&0o077)
    con=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=5)
    try:
        con.execute('BEGIN')
        row=con.execute('SELECT context,sha256,health FROM meta WHERE id=1').fetchone()
        require(row is not None and json.loads(row[0])==identity and row[1]==quality.digest(identity))
        tasks=[]
        for request, in con.execute('SELECT request_id FROM tasks ORDER BY ticket,request_id').fetchall():
            try:tasks.append(state(con,request))
            except (ValueError,KeyError,TypeError):
                tasks.append(dict(request_id=request,stage='integrity_rejected',owner='cto',delivery_approval=False))
        return dict(stage='available',health=json.loads(row[2]) if row[2] else None,tasks=tasks,delivery_approval=False)
    finally:con.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--config',required=True)
    parser.add_argument('--watch',action='store_true');parser.add_argument('--interval',type=int,default=15)
    args=parser.parse_args();require(5<=args.interval<=60)
    config=configuration(args.config);authority=Authority(config['namespace'],config['image']);stopped=False
    def stop(*_):
        nonlocal stopped
        stopped=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    previous=None
    while not stopped:
        try:result=tick(authority,config['repositories'],config['private'])
        except Pending:result=dict(stage='busy_or_pending',delivery_approval=False,model_calls=0)
        fingerprint=quality.digest({k:v for k,v in result.items() if k!='observed'})
        if not args.watch or fingerprint!=previous or result.get('observed'):
            print(json.dumps(result,sort_keys=True),flush=True);previous=fingerprint
        if not args.watch:break
        for _ in range(args.interval):
            if stopped:break
            time.sleep(1)


if __name__=='__main__':main()
