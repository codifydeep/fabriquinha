"""Bounded, content-addressed snapshots before native scratch cleanup."""
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from delivery_receipts import EvidenceStore


def snapshot(conn,task_id,workspace):
    database=conn.execute('PRAGMA database_list').fetchone()[2]
    if not database or not re.fullmatch(r't_[a-z0-9]+',task_id):
        raise ValueError('snapshot requires durable board and canonical task id')
    board=Path(database).resolve().parent
    root=Path(workspace).resolve(strict=True)
    if not root.is_relative_to(board/'workspaces'):
        raise ValueError('scratch snapshot is outside its board')
    owner=root.stat()
    store=EvidenceStore(board/'evidence',task_id,owner=(owner.st_uid,owner.st_gid))
    artifacts=[]
    empty=[]
    total=0
    paths=sorted(root.rglob('*'))
    if len(paths)>1000:
        raise ValueError('scratch exceeds bounded snapshot; retain workspace')
    signatures={}
    for path in paths:
        if '__pycache__' in path.relative_to(root).parts:
            continue
        if path.is_symlink():
            raise ValueError('scratch has symlink; retain workspace for explicit archive')
        if not path.is_file():
            continue
        relative=str(path.relative_to(root))
        size=path.stat().st_size
        total+=size
        if total>64*1024*1024:
            raise ValueError('scratch exceeds 64 MiB; retain workspace')
        if size==0:
            empty.append(relative)
            signatures[relative]=hashlib.sha256(b'').hexdigest()
        else:
            item=store.capture(root,relative)
            artifacts.append(item)
            signatures[relative]=item['sha256']
    digest=store.save(dict(kind='scratch-snapshot',task=task_id,board=board.name,
        artifacts=artifacts,empty_files=empty))
    store.load(digest)
    # A changing or newly created file must not be silently lost during cleanup.
    current={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest()
        for p in root.rglob('*') if p.is_file() and '__pycache__' not in p.relative_to(root).parts}
    if current!=signatures:
        raise ValueError('scratch changed while archiving; retain workspace')
    pointer=store.root/'latest.json'
    with tempfile.NamedTemporaryFile(mode='w',dir=pointer.parent,delete=False) as out:
        temporary=Path(out.name)
        json.dump(dict(task=task_id,sha256=digest),out)
        out.flush()
        os.fsync(out.fileno())
    if os.geteuid()==0: os.chown(temporary,owner.st_uid,owner.st_gid)
    try: os.replace(temporary,pointer)
    finally: temporary.unlink(missing_ok=True)
    return digest
