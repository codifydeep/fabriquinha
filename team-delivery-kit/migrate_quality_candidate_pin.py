"""Quiescent authority-pin migration, never evidence conversion or crash reset.

The owned service must be disabled AND unloaded. The new controller must already
be sealed, idle and execution-disabled. Namespace, repository map and private
home cannot change. Both kernel locks fence ticks; compare-and-swap plus private
archives let an interrupted migration resume without replacing any work history.
"""
import argparse
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import sqlite3
import stat
import subprocess
import tempfile
import uuid
import quality_candidate_service as service
import quality_candidate_dispatch as dispatch
from quality_candidate_authority import Authority
from quality_git_candidate import journal,quality,require
from qualify_quality_red_observer import require_idle


def label(namespace):return 'com.codifydeep.delivery-kit.'+namespace.removeprefix('delivery-kit-')+'.quality-candidates'


class Effects:
    def about(self,namespace,image):return Authority(namespace,image).about()
    def idle(self,namespace):return require_idle(namespace)
    def stopped(self,namespace):
        require(os.sys.platform=='darwin')
        domain='gui/'+str(os.getuid());name=label(namespace)
        result=subprocess.run(['launchctl','print',domain+'/'+name],capture_output=True,text=True,timeout=10)
        require(result.returncode==113)
        disabled=subprocess.check_output(['launchctl','print-disabled',domain],text=True,timeout=10)
        require(re.search(r'"'+re.escape(name)+r'"\s*=>\s*true',disabled) is not None)
    def helpers(self,namespace):
        result=subprocess.check_output(['docker','ps','-aq','--filter',
            'label=com.docker.compose.project='+namespace+'-tests'],text=True,timeout=15)
        require(not result.strip())
    def login(self,namespace):return Path.home()/'Library'/'LaunchAgents'/(label(namespace)+'.plist')
    def register(self,path,pin):return service.register(path,pin,native_paths=True)


def read(path):
    path=Path(path);require(path.is_absolute() and path.resolve()==path and not path.is_symlink())
    info=path.stat();require(stat.S_ISREG(info.st_mode) and info.st_uid==os.getuid()
        and info.st_nlink==1 and not info.st_mode&0o077 and info.st_size<=1048576)
    return path.read_bytes()


def digest(raw):return hashlib.sha256(raw).hexdigest()


def cas(path,raw,expected):
    path=Path(path)
    if path.exists():
        current=read(path)
        if current==raw:return
        require(digest(current)==expected)
    else:require(expected is None and not path.is_symlink())
    fd,temporary=tempfile.mkstemp(prefix=path.name+'.',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as out:out.write(raw);out.flush();os.fsync(out.fileno())
        os.replace(temporary,path)
        parent=os.open(path.parent,os.O_RDONLY)
        try:os.fsync(parent)
        finally:os.close(parent)
    finally:
        if os.path.exists(temporary):os.unlink(temporary)


def folder(path):
    path=Path(path);require(path.is_absolute() and path.resolve()==path and not path.is_symlink())
    path.mkdir(mode=0o700,exist_ok=True)
    require(path.stat().st_uid==os.getuid() and not path.stat().st_mode&0o077)
    return path


def children(private):
    result={}
    for family in ('quality-git-candidates','quality-delivery-exports'):
        root=private/family;require(not root.is_symlink())
        rows={}
        if root.exists():
            for path in sorted(root.rglob('*')):
                require(not path.is_symlink())
                if path.is_file():
                    require(path.stat().st_nlink==1 and path.stat().st_uid==os.getuid())
                    with path.open('rb') as stream:sha=hashlib.file_digest(stream,'sha256').hexdigest()
                    rows[path.relative_to(root).as_posix()]=sha
                else:require(path.is_dir())
        result[family]=dict(exists=root.exists(),files=rows)
    return quality.digest(result)


def queue(con):
    row=con.execute('SELECT context,sha256,cursor,ticket,health FROM meta WHERE id=1').fetchone()
    require(row is not None and quality.digest(json.loads(row[0]))==row[1])
    rows=con.execute('SELECT request_id,state,sha256,ticket FROM tasks ORDER BY request_id').fetchall()
    for request,*_ in rows:dispatch.canonical(request);dispatch.state(con,request)
    return row,quality.digest(dict(cursor=row[2],ticket=row[3],health=row[4],tasks=rows)),len(rows)


def probe(fx,namespace,image):
    about=fx.about(namespace,image)
    require(about['maintenance'] is True and about['v2_enabled'] is False
        and about['implementation_enabled'] is False and about.get('queue_supported') is True)
    fx.idle(namespace);fx.stopped(namespace);fx.helpers(namespace)


def migrate(old_path,old_pin,new_image,operation,*,effects=None):
    dispatch.canonical(operation)
    value,_,old_service=service.config(old_path,old_pin);namespace=value['namespace'];private=Path(value['private'])
    require(re.fullmatch('sha256:[a-f0-9]{64}',new_image) and new_image!=value['image'])
    archive=folder(folder(private/'backups')/('candidate-pin-migration-'+operation))
    identity=dict(operation=operation,namespace=namespace,old_config=str(Path(old_path)),old_pin=old_pin,new_image=new_image)
    intent=archive/'intent.json';completed=archive/'result.json'
    if completed.exists():
        result=json.loads(read(completed));require(result['identity']==identity);return result
    fx=effects or Effects();probe(fx,namespace,new_image)
    queue_token=str(uuid.uuid5(uuid.NAMESPACE_URL,'quality-candidate-dispatch:'+namespace))
    with ExitStack() as stack:
        svc=stack.enter_context(journal(private,service.token(namespace),family='quality-candidate-dispatch'))
        q=stack.enter_context(journal(private,queue_token,family='quality-candidate-dispatch')).with_suffix('.sqlite')
        require(q.is_file());read_info=q.stat()
        require(not q.is_symlink() and read_info.st_nlink==1 and read_info.st_uid==os.getuid() and not read_info.st_mode&0o077)
        con=sqlite3.connect(q,timeout=5)
        stack.callback(con.close)
        old_context=dispatch.context(dispatch.Authority(namespace,value['image']),value['repositories'])
        new_value={**value,'image':new_image};new_context={**old_context,'image':new_image}
        configdir=folder(private/'controller-config');new_config=configdir/('quality-candidate-'+operation+'.json')
        encoded=json.dumps(new_value,sort_keys=True).encode();new_pin=digest(encoded)
        new_service=dict(old_service,config=str(new_config),config_sha256=new_pin)
        row,history,count=queue(con)
        if not intent.exists():
            require(json.loads(row[0])==old_context)
            previous=service.load(svc,old_service)
            require(previous is None or previous['stage']!='tick_intent')
            login=fx.login(namespace);login_raw=read(login) if login.exists() else None
            if login_raw is not None:
                registered=plistlib.loads(login_raw)
                require(registered['Label']==label(namespace) and registered['ProgramArguments']==[
                    os.sys.executable,'-u',str(service.ROOT/'quality_candidate_service.py'),
                    '--config',str(Path(old_path)),'--pin',old_pin])
                service.write_once(archive/'old-login.plist',login_raw)
            service.write_once(archive/'old-config.json',read(Path(old_path)))
            if svc.exists():service.write_once(archive/'old-service.json',read(svc))
            state=dict(identity=identity,old_context=old_context,new_context=new_context,history_sha256=history,
                task_count=count,service_state=previous,children_sha256=children(private),
                login=str(login),login_sha256=digest(login_raw) if login_raw is not None else None)
            service.write_once(intent,json.dumps(state,sort_keys=True).encode())
        else:
            state=json.loads(read(intent));require(state['identity']==identity and state['old_context']==old_context
                and state['new_context']==new_context and state['history_sha256']==history and state['task_count']==count)
        require(json.loads(row[0]) in (old_context,new_context) and children(private)==state['children_sha256'])
        backup=archive/'queue.sqlite'
        if not backup.exists():
            require(json.loads(row[0])==old_context)
            fd=os.open(backup,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
            saved=sqlite3.connect(backup)
            try:con.backup(saved)
            finally:saved.close()
        backup_info=backup.stat()
        require(not backup.is_symlink() and backup.resolve()==backup and stat.S_ISREG(backup_info.st_mode)
            and backup_info.st_uid==os.getuid() and backup_info.st_nlink==1 and not backup_info.st_mode&0o077)
        saved=sqlite3.connect(backup.as_uri()+'?mode=ro',uri=True)
        try:
            require(saved.execute('PRAGMA integrity_check').fetchone()[0]=='ok')
            backup_row,backup_history,backup_count=queue(saved)
            require(json.loads(backup_row[0])==old_context and backup_history==history and backup_count==count)
        finally:saved.close()
        with backup.open('rb') as stream:os.fsync(stream.fileno())
        service.write_once(new_config,encoded)
        fx.stopped(namespace)
        with con:
            if json.loads(row[0])==old_context:
                changed=con.execute('UPDATE meta SET context=?,sha256=? WHERE id=1 AND context=? AND sha256=?',
                    (json.dumps(new_context,sort_keys=True),quality.digest(new_context),row[0],row[1]))
                require(changed.rowcount==1)
        after,after_history,after_count=queue(con)
        require(json.loads(after[0])==new_context and after_history==history and after_count==count)
        previous=state['service_state']
        if previous is not None:
            current=json.loads(read(svc))
            require(current['context'] in (old_service,new_service) and current['state']==previous
                and current['state_sha256']==quality.digest(previous)
                and current['context_sha256']==quality.digest(current['context']))
            new_bytes=json.dumps(dict(context=new_service,state=previous,
                context_sha256=quality.digest(new_service),state_sha256=quality.digest(previous)),sort_keys=True).encode()
            cas(svc,new_bytes,digest(read(archive/'old-service.json')))
            require(service.load(svc,new_service)==previous)
        else:require(not svc.exists())
        registration=fx.register(new_config,new_pin)
        if state['login_sha256'] is not None:
            cas(Path(state['login']),read(Path(registration['plist'])),state['login_sha256'])
        require(children(private)==state['children_sha256'])
        probe(fx,namespace,new_image)
        result=dict(identity=identity,stage='pins_migrated_service_stopped',new_config=str(new_config),new_pin=new_pin,
            registration=registration,task_count=count,history_sha256=history,task_states_preserved=True,
            crash_state_preserved=True,child_journals_preserved=True,private_home_preserved=True,repository_map_preserved=True,
            backup_integrity='ok',model_calls=0,delivery_approval=False)
        service.write_once(completed,json.dumps(result,sort_keys=True).encode());return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('old-config','old-pin','image','operation'):parser.add_argument('--'+key,required=True)
    args=parser.parse_args()
    print(json.dumps(migrate(args.old_config,args.old_pin,args.image,args.operation),sort_keys=True))
