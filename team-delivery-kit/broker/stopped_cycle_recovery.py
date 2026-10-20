"""Operator-only repair of legacy cycle bookkeeping after the core is stopped.

The host wrapper must prove the exact sole Compose controller is stopped. No
worker/API entrypoint exists. Back up and restore-check first; retain every
workflow, grant and snapshot. A dead cycle becomes interrupted, never completed.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import uuid
from contextlib import closing


def require(value):
    if not value:raise ValueError('exact stopped legacy cycle recovery required')


def file_sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1048576),b''):h.update(chunk)
    return h.hexdigest()


def recover(source,identity):
    require(set(identity)=={'operation_id','namespace','container_id','state'})
    operation=identity['operation_id'];require(str(uuid.UUID(operation))==operation
        and bool(re.fullmatch('delivery-kit-[a-z0-9-]{1,48}',identity['namespace']))
        and bool(re.fullmatch('[a-f0-9]{64}',identity['container_id'])))
    stopped=identity['state'];require(set(stopped)=={'Running','Pid','Status','StartedAt','FinishedAt'}
        and stopped.get('Running') is False and type(stopped.get('Pid')) is int and stopped['Pid']==0
        and stopped.get('Status')=='exited' and isinstance(stopped.get('FinishedAt'),str)
        and stopped['FinishedAt'] and not stopped['FinishedAt'].startswith('0001'))
    source=Path(source);require(source.is_file() and not source.is_symlink())
    backup=source.parent/('legacy-cycle-backup-'+operation+'.sqlite')
    proof=source.parent/('legacy-cycle-restore-'+operation+'.sqlite')
    with closing(sqlite3.connect(source)) as c,c:
        c.row_factory=sqlite3.Row
        c.execute('CREATE TABLE IF NOT EXISTS stopped_cycle_recoveries(operation_id TEXT PRIMARY KEY,receipt TEXT)')
        old=c.execute('SELECT receipt FROM stopped_cycle_recoveries WHERE operation_id=?',(operation,)).fetchone()
        if old:
            receipt=json.loads(old[0]);require(receipt['identity']==identity and file_sha(backup)==receipt['backup_sha256'])
            return receipt
        row=c.execute('SELECT stage,receipt FROM controller_maintenance WHERE operation_id=?',(operation,)).fetchone()
        require(row and row['stage']=='draining' and json.loads(row['receipt'])['namespace']==identity['namespace'])
        require(not c.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone())
        require(not c.execute('SELECT 1 FROM grants g LEFT JOIN leases l USING(request_id) WHERE g.used=1 '
            'AND g.deadline>unixepoch() AND l.request_id IS NULL').fetchone())
        cycles=[r[0] for r in c.execute("SELECT cycle_id FROM controller_maintenance_cycles WHERE namespace=? AND stage='active' ORDER BY cycle_id",(identity['namespace'],))]
        require(cycles)
        c.execute('CREATE TABLE IF NOT EXISTS controller_cycle_owners(cycle_id TEXT PRIMARY KEY,identity TEXT)')
        c.execute('CREATE TABLE IF NOT EXISTS controller_cycle_interruptions(cycle_id TEXT PRIMARY KEY,receipt TEXT)')
        require(not any(c.execute('SELECT 1 FROM controller_cycle_owners WHERE cycle_id=?',(cycle,)).fetchone() for cycle in cycles))
        require(not backup.exists() and not proof.exists())  # Unknown backup effects are observed, not repeated.
        c.commit()
        fd=os.open(backup,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
        with closing(sqlite3.connect(backup)) as saved,saved:
            c.backup(saved);require(saved.execute('PRAGMA integrity_check').fetchone()[0]=='ok')
            fd=os.open(proof,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
            with closing(sqlite3.connect(proof)) as restored,restored:
                saved.backup(restored);require(restored.execute('PRAGMA integrity_check').fetchone()[0]=='ok')
                for (table,) in saved.execute("SELECT name FROM sqlite_master WHERE type='table'"):
                    name='"'+table.replace('"','""')+'"'
                    require(saved.execute('SELECT count(*) FROM '+name).fetchone()==restored.execute('SELECT count(*) FROM '+name).fetchone())
                require(restored.execute('SELECT receipt FROM controller_maintenance WHERE operation_id=?',(operation,)).fetchone()[0]==row['receipt'])
        proof.unlink()  # Only this newly created temporary restore proof.
        receipt=dict(operation='stopped_legacy_cycle_recovery_v1',identity=identity,backup=str(backup),backup_sha256=file_sha(backup),
            backup_integrity='ok',restore_integrity='ok',interrupted_cycles=cycles,cycle_completed=False,
            source_reset=False,grants_replayed=False,delivery_approval=False)
        c.execute('BEGIN IMMEDIATE')
        require(c.execute('SELECT stage FROM controller_maintenance WHERE operation_id=?',(operation,)).fetchone()[0]=='draining')
        for cycle in cycles:
            require(c.execute("UPDATE controller_maintenance_cycles SET stage='interrupted' WHERE cycle_id=? AND namespace=? AND stage='active'",(cycle,identity['namespace'])).rowcount==1)
            c.execute('INSERT INTO controller_cycle_interruptions VALUES(?,?)',(cycle,json.dumps(receipt,sort_keys=True)))
        c.execute('INSERT INTO stopped_cycle_recoveries VALUES(?,?)',(operation,json.dumps(receipt,sort_keys=True)))
        return receipt


if __name__=='__main__':
    require(len(sys.argv)==2)
    print(json.dumps(recover('/state/leases.sqlite',json.loads(sys.argv[1])),sort_keys=True))
