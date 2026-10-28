"""Extract a stopped-installation backup for offline integrity inspection only.

Never constructs Runtime, starts a service, resumes dispatch, or restores an
old provider counter into a live volume. Private output contains installation
secrets; keep it outside Git and do not use it as another runnable installation.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import sqlite3
import sys
import tarfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from fabriquinha.artifacts import Store
from fabriquinha.effects import write_json


def verify(archive,destination,counter):
    archive=Path(archive).resolve();destination=Path(destination).resolve()
    if destination.exists():raise ValueError('fresh private inspection destination required')
    if destination.is_relative_to(ROOT):
        import subprocess
        if subprocess.run(['git','-C',str(ROOT),'check-ignore','--quiet',str(destination)]).returncode:
            raise ValueError('Git-ignored inspection directory required')
    destination.mkdir(parents=True,mode=0o700)
    with tarfile.open(archive,'r:gz') as stream:
        entries=stream.getmembers();names=set()
        for entry in entries:
            path=PurePosixPath(entry.name)
            if (path.is_absolute() or '..' in path.parts or not path.parts or path.parts[0]!='installation'
                    or entry.name in names or not (entry.isfile() or entry.isdir() or entry.islnk())):
                raise ValueError('bounded installation entries required; no symlinks or special files')
            names.add(entry.name)
        for entry in entries:
            if entry.islnk():
                target=PurePosixPath(entry.linkname)
                if target.is_absolute() or '..' in target.parts or entry.linkname not in names:
                    raise ValueError('hardlink target must remain inside this archive')
        stream.extractall(destination,filter='data')
        checked=0
        for entry in entries:
            if entry.isfile() or entry.islnk():
                with stream.extractfile(entry) as original:
                    expected=hashlib.sha256(original.read()).hexdigest()
                assert hashlib.sha256((destination/entry.name).read_bytes()).hexdigest()==expected
                checked+=1
    root=destination/'installation'
    # Read-only SQLite, no controller binding or profile migration.
    with sqlite3.connect((root/'home/kanban.db').as_uri()+'?mode=ro',uri=True) as conn:
        assert conn.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert conn.execute('SELECT COUNT(*) FROM task_runs WHERE ended_at IS NULL').fetchone()[0]==0
        cards=conn.execute('SELECT COUNT(*) FROM tasks').fetchone()[0]
        runs=conn.execute('SELECT COUNT(*) FROM task_runs').fetchone()[0]
    control=json.loads((root/'control.json').read_bytes())
    assert control['paused'] is True
    policy=json.loads((root/'provider-policy.json').read_bytes())
    assert policy['enabled'] is False
    store=Store(root/'private');objects=receipts=0
    for path in (store.root/'objects').iterdir():
        if path.name.startswith('.'):raise ValueError('unfinished snapshot requires diagnosis')
        store.tree(path.name);objects+=1
    for path in (store.root/'receipts').glob('*.json'):
        store.receipt(path.stem);receipts+=1
    count=json.loads(Path(counter).read_bytes())
    if set(count)!={'calls'} or type(count['calls']) is not int or count['calls']<0:
        raise ValueError('preserved counter is invalid')
    result=dict(archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),files_verified=checked,
        sqlite_integrity=True,cards=cards,historical_runs=runs,open_runs=0,snapshots_verified=objects,
        receipts_verified=receipts,paused=True,provider_enabled=False,preserved_counter=count['calls'],
        counter_written_to_live_volume=False,services_started=0,model_calls=0,
        production_restart_qualified=False,external_effect_reconciliation_qualified=False)
    write_json(destination/'inspection-receipt.json',result)
    print(json.dumps(result,indent=2));return result

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive',type=Path,required=True)
    parser.add_argument('--destination',type=Path,required=True)
    parser.add_argument('--counter',type=Path,required=True)
    args=parser.parse_args();os.umask(0o077)
    verify(args.archive,args.destination,args.counter)
