"""Explicit backup-only compaction; never touches live databases or Docker.

Gzip is lossless. Before retiring the uncompressed copy, verify SQLite, the
compressed round trip, source identity and absence of WAL/SHM/journal companions.
Keep the newest two eligible databases uncompressed in each explicitly supplied
backup root. Dry-run is the default. Receipts are private, never publication data.
"""
import argparse
from contextlib import closing
import gzip
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import time
import uuid


def digest(path, compressed=False):
    value=hashlib.sha256()
    with (gzip.open(path,'rb') if compressed else path.open('rb')) as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):value.update(chunk)
    return value.hexdigest()


def identity(path):
    s=path.lstat()
    if not stat.S_ISREG(s.st_mode) or s.st_nlink!=1:raise ValueError('ordinary single-link backup required')
    return (s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)


def companions(path):return any(Path(str(path)+suffix).exists() for suffix in ('-wal','-shm','-journal'))


def root_path(value):
    root=Path(value).absolute()
    if root!=root.resolve(strict=True) or root.name!='backups' or not root.is_dir():
        raise ValueError('explicit real backups directory required')
    return root


def candidates(root):
    found=[]
    for directory,dirs,files in os.walk(root,followlinks=False):
        dirs[:]=[d for d in dirs if not (Path(directory)/d).is_symlink()]
        for name in files:
            path=Path(directory)/name
            if path.suffix not in ('.sqlite','.db') or path.is_symlink():continue
            if path.resolve()!=path or not path.is_relative_to(root):continue
            try:
                key=identity(path)
                if key[2]<1024*1024 or companions(path):continue
                with path.open('rb') as stream:
                    if stream.read(16)!=b'SQLite format 3\0':continue
                found.append((path,key))
            except OSError:continue
    return sorted(found,key=lambda row:row[1][3],reverse=True)


def compact(path, expected):
    if identity(path)!=expected or companions(path):raise ValueError('backup changed or has companions')
    # Backup-only and no companions were verified above. Immutable mode avoids
    # SQLite itself creating empty WAL/SHM files while inspecting a closed copy.
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro&immutable=1',uri=True)) as con:
        if con.execute('PRAGMA quick_check').fetchall()!=[('ok',)]:raise ValueError('SQLite quick_check failed')
    target=Path(str(path)+'.gz')
    temporary=path.with_name(path.name+'.compact-'+uuid.uuid4().hex)
    source_hash=hashlib.sha256()
    try:
        with path.open('rb') as source,os.fdopen(os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'wb') as raw:
            with gzip.GzipFile(filename='',mode='wb',fileobj=raw,compresslevel=6,mtime=0) as destination:
                for chunk in iter(lambda:source.read(1024*1024),b''):
                    source_hash.update(chunk);destination.write(chunk)
            raw.flush();os.fsync(raw.fileno())
        sha=source_hash.hexdigest()
        if digest(temporary,True)!=sha:raise ValueError('compressed round trip mismatch')
        if identity(path)!=expected or companions(path) or digest(path)!=sha:raise ValueError('source changed during compression')
        if temporary.stat().st_size>=expected[2]*0.9:raise ValueError('insufficient compression benefit; original retained')
        if target.exists() or target.is_symlink():raise ValueError('existing archive retained; no overwrite')
        os.link(temporary,target)  # Atomic no-clobber publication on the same filesystem.
        temporary.unlink();os.utime(target,ns=(expected[3],expected[3]))
        if identity(path)!=expected or companions(path):raise ValueError('source changed before retirement')
        compressed_size=target.stat().st_size
        path.unlink()
        return dict(path=str(path),archive=str(target),sha256=sha,original_bytes=expected[2],compressed_bytes=compressed_size)
    finally:
        if temporary.exists():temporary.unlink()


def run(root,apply=False):
    root=root_path(root);found=candidates(root);selected=found[2:]
    summary=dict(root=str(root),apply=apply,eligible=len(found),keep_newest_uncompressed=min(2,len(found)),
        selected=len(selected),selected_bytes=sum(key[2] for _,key in selected))
    if not apply:return summary
    receipt=root/('compaction-'+time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8]+'.jsonl')
    saved=0;done=0;errors=0
    with os.fdopen(os.open(receipt,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'w') as log:
        for path,key in selected:
            try:
                row=compact(path,key);saved+=row['original_bytes']-row['compressed_bytes'];done+=1
            except (OSError,ValueError,sqlite3.Error) as error:
                row=dict(path=str(path),retained=True,error_type=type(error).__name__);errors+=1
            log.write(json.dumps(row,sort_keys=True)+'\n');log.flush();os.fsync(log.fileno())
    return {**summary,'compacted':done,'retained_on_error':errors,'logical_bytes_saved':saved,'receipt':str(receipt)}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',action='append',required=True);p.add_argument('--apply',action='store_true')
    args=p.parse_args()
    for root in args.root:print(json.dumps(run(root,args.apply),sort_keys=True),flush=True)
