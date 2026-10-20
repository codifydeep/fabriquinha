"""Lossless sealed-state backup with one scratch allocation and real restore.

The scratch is zeroed in place before gzip restoration: validation cannot pass
by accidentally reading its old SQLite bytes. No current or historical bank is
overwritten. The operator wrapper owns maintenance/lease authorization.
"""
from contextlib import closing
import gzip
import hashlib
import json
import os
from pathlib import Path
import sqlite3


def require(value):
    if not value:raise ValueError('compressed backup verification failed')


def file_sha(path,compressed=False):
    h=hashlib.sha256()
    with (gzip.open(path,'rb') if compressed else path.open('rb')) as f:
        for chunk in iter(lambda:f.read(1048576),b''):h.update(chunk)
    return h.hexdigest()


def restore_zeroed(archive,scratch,size):
    with scratch.open('r+b') as target:
        remaining=size
        while remaining:
            n=min(1048576,remaining);target.write(bytes(n));remaining-=n
        target.flush();os.fsync(target.fileno());target.seek(0)
        with gzip.open(archive,'rb') as source:
            written=0
            for chunk in iter(lambda:source.read(1048576),b''):
                written+=len(chunk);require(written<=size);target.write(chunk)
        require(written==size);target.flush();os.fsync(target.fileno())


def backup(con,archive,scratch,maintenance,max_archive_bytes=67108864):
    archive,scratch=Path(archive),Path(scratch)
    require(archive.parent==scratch.parent and archive!=scratch and not archive.exists() and not archive.is_symlink()
        and not scratch.exists() and not scratch.is_symlink() and type(max_archive_bytes) is int and 0<max_archive_bytes<=268435456)
    fd=os.open(scratch,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);os.close(fd)
    with closing(sqlite3.connect(scratch)) as saved:
        con.backup(saved);require(saved.execute('PRAGMA integrity_check').fetchone()[0]=='ok')
        tables=[r[0] for r in saved.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        counts={table:saved.execute('SELECT count(*) FROM "'+table.replace('"','""')+'"').fetchone()[0] for table in tables}
    size=scratch.stat().st_size;raw_sha=file_sha(scratch)
    with scratch.open('rb') as source,os.fdopen(os.open(archive,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'wb') as raw:
        with gzip.GzipFile(filename='',mode='wb',fileobj=raw,compresslevel=6,mtime=0) as compressed:
            for chunk in iter(lambda:source.read(1048576),b''):
                compressed.write(chunk);require(raw.tell()<=max_archive_bytes)
        raw.flush();os.fsync(raw.fileno());require(raw.tell()<=max_archive_bytes)
    require(file_sha(archive,True)==raw_sha)
    restore_zeroed(archive,scratch,size)
    require(scratch.stat().st_size==size and file_sha(scratch)==raw_sha)
    with closing(sqlite3.connect(scratch)) as restored:
        require(restored.execute('PRAGMA integrity_check').fetchone()[0]=='ok')
        row=restored.execute('SELECT receipt FROM controller_maintenance WHERE operation_id=?',(maintenance['operation_id'],)).fetchone()
        require(row and json.loads(row[0])==maintenance)
        for table,count in counts.items():
            require(restored.execute('SELECT count(*) FROM "'+table.replace('"','""')+'"').fetchone()[0]==count)
    scratch.unlink()  # Exact temporary proof created here; archive remains durable.
    return dict(operation='sealed_gzip_backup_restore_v1',path=str(archive),encoding='gzip',
        sha256=raw_sha,archive_sha256=file_sha(archive),uncompressed_bytes=size,compressed_bytes=archive.stat().st_size,
        backup_integrity='ok',restore_integrity='ok',restore_method='zeroed_scratch_then_gzip_restore',
        active_leases=0,native_active=0,source_reset=False,delivery_approval=False)
