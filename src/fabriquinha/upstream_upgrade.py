"""Cold, reversible upstream binding migration; never resumes dispatch.

The operator stops auxiliary readers/writers first. A verified cold backup is
mandatory. The external provider meter is not copied, restored or modified.
"""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
from .effects import write_json
from .runtime import Owner

BINDINGS=('installation.json','control.json')

def manifest(root):
    result={}
    for path in sorted(Path(root).rglob('*')):
        if path.is_symlink():raise ValueError('symlink in cold state')
        if path.is_file():result[str(path.relative_to(root))]=hashlib.sha256(path.read_bytes()).hexdigest()
        elif not path.is_dir():raise ValueError('special file in cold state')
    return result

def prepare(runtime,backup,upstream):
    root=runtime.root;backup=Path(backup).resolve();upstream=Path(upstream).resolve()
    if backup.exists() or backup.is_relative_to(root):raise ValueError('fresh external backup required')
    commit=subprocess.check_output(['git','-C',str(upstream),'rev-parse','HEAD'],text=True).strip()
    if subprocess.check_output(['git','-C',str(upstream),'status','--porcelain'],text=True).strip():
        raise ValueError('clean upstream required')
    if commit!='bf0203a794a07aac3ff764972ab9087baa4e4f4e':raise ValueError('qualified destination required')
    with Owner(root),runtime.control.lock():
        control=runtime.control.read()
        if control['error'] or not control['paused']:raise ValueError('valid durable pause required')
        from .kanban_lane import native
        _,kbc,_=native()
        with kbc.connect_closing() as conn:
            if not runtime.pause_status(conn)['drained']:raise ValueError('drained installation required')
        for path in (root/'home').rglob('*.db'):
            with closing(sqlite3.connect(path)) as conn:
                if conn.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('database integrity')
                if conn.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()[0]!=0:raise ValueError('database busy')
        if control['upstream']!='e06df9c2eae6901f4c88f464e0ae6e753c0428b8':raise ValueError('qualified source required')
        before=manifest(root)
        backup.mkdir(mode=0o700,parents=True)
        shutil.copytree(root,backup/'state')
        if manifest(root)!=before or manifest(backup/'state')!=before:raise ValueError('state changed during backup')
        plan=dict(version=1,root=str(root),before=before,old=control['upstream'],new=commit,
                  project=control['project'],episode=control['episode'],drained=True)
        if plan['old']==plan['new']:raise ValueError('different upstream required')
        write_json(backup/'plan.json',plan)
        return plan

def apply(root,backup,*,rollback=False):
    """Restart-safe two-file transaction; any unrelated change refuses recovery."""
    root=Path(root).resolve();backup=Path(backup).resolve()
    plan=json.loads((backup/'plan.json').read_bytes())
    if plan['version']!=1 or plan['root']!=str(root) or plan['drained'] is not True:
        raise ValueError('exact prepared migration required')
    if manifest(backup/'state')!=plan['before']:raise ValueError('backup integrity')
    before={name:json.loads((backup/'state'/name).read_bytes()) for name in BINDINGS}
    control=before['control.json']
    if (control['paused'] is not True or control['episode']!=plan['episode']
            or any(v['project']!=plan['project'] or v['upstream']!=plan['old'] for v in before.values())):
        raise ValueError('scoped paused source required')
    after={name:{**value,'upstream':plan['new']} for name,value in before.items()}
    import fcntl
    with Owner(root),(root/'control.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        actual=manifest(root)
        if {k:v for k,v in actual.items() if k not in BINDINGS}!={k:v for k,v in plan['before'].items() if k not in BINDINGS}:
            raise ValueError('cold state drift; migration refused')
        for name in BINDINGS:
            if json.loads((root/name).read_bytes()) not in (before[name],after[name]):raise ValueError('binding drift')
        for name,value in (before if rollback else after).items():write_json(root/name,value)
        return dict(upstream=plan['old'] if rollback else plan['new'],paused=True,
                    episode=plan['episode'],delivery_approval=False)
