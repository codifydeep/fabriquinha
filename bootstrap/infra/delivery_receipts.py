"""Content-addressed private evidence, independent of disposable worktrees."""
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile


class EvidenceStore:
    def __init__(self,root,attempt,owner=None):
        if not re.fullmatch(r'[A-Za-z0-9_-]+',attempt):
            raise ValueError('invalid evidence attempt')
        self.attempt=attempt
        self.owner=owner
        self.root=Path(root)/attempt
        if owner is not None and os.geteuid()==0:
            for directory in (Path(root),self.root):
                if directory.is_symlink(): raise ValueError('evidence directory must not be a symlink')
                directory.mkdir(parents=True,exist_ok=True,mode=0o700)
                os.chown(directory,*owner)
        for kind in ('blobs','receipts'):
            (self.root/kind).mkdir(parents=True,exist_ok=True,mode=0o700)
            if owner is not None and os.geteuid()==0:
                if (self.root/kind).is_symlink(): raise ValueError('evidence directory must not be a symlink')
                os.chown(self.root/kind,*owner)

    def _write(self,kind,data):
        digest=hashlib.sha256(data).hexdigest()
        target=self.root/kind/digest
        temporary=None
        try:
            with tempfile.NamedTemporaryFile(dir=target.parent,delete=False) as stream:
                temporary=Path(stream.name)
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            if self.owner is not None and os.geteuid()==0: os.chown(temporary,*self.owner)
            os.link(temporary,target)
        except FileExistsError:
            if target.read_bytes()!=data:
                raise ValueError('existing evidence differs from its content hash')
            if self.owner is not None and os.geteuid()==0: os.chown(target,*self.owner)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return digest

    def capture(self,workspace,relative):
        root=Path(workspace).resolve(strict=True)
        path=(root/relative).resolve(strict=True)
        if Path(relative).is_absolute() or not path.is_relative_to(root) or not path.is_file():
            raise ValueError('evidence must be a file inside the assigned workspace')
        if path.stat().st_size>16*1024*1024:
            raise ValueError('split evidence files larger than 16 MiB into bounded artifacts')
        data=path.read_bytes()
        return self.capture_bytes(relative,data)

    def capture_bytes(self,relative,data):
        if Path(relative).is_absolute() or '..' in Path(relative).parts or not relative:
            raise ValueError('evidence path must be repository-relative')
        if not isinstance(data,bytes) or not data or len(data)>16*1024*1024:
            raise ValueError('empty evidence is not proof')
        return dict(path=str(relative),sha256=self._write('blobs',data),bytes=len(data))

    def save(self,proof):
        data=json.dumps(dict(proof,attempt=self.attempt),sort_keys=True,ensure_ascii=False).encode()
        return self._write('receipts',data)

    def load(self,digest):
        if not re.fullmatch(r'[0-9a-f]{64}',digest):
            raise ValueError('invalid receipt hash')
        raw=(self.root/'receipts'/digest).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=digest:
            raise ValueError('receipt checksum mismatch')
        receipt=json.loads(raw)
        if receipt.get('attempt')!=self.attempt:
            raise ValueError('receipt belongs to another attempt')
        for artifact in receipt.get('artifacts',[]):
            sha=artifact.get('sha256','')
            if not re.fullmatch(r'[0-9a-f]{64}',sha):
                raise ValueError('invalid blob hash')
            content=(self.root/'blobs'/sha).read_bytes()
            if hashlib.sha256(content).hexdigest()!=sha or len(content)!=artifact['bytes']:
                raise ValueError('evidence blob checksum mismatch')
        return receipt


def record_verified(release,task,proof):
    from coordination_store import CoordinationStore
    attempt=release['attempt']
    evidence=EvidenceStore('/opt/data/governance/evidence',attempt)
    digest=evidence.save(dict(proof,task=task))
    evidence.load(digest)  # Never attest a receipt whose referenced bytes are absent.
    store=CoordinationStore('/opt/data/governance/coordination.db')
    try:
        with store.transaction(attempt):
            store._put(attempt,'verified_receipt',digest,dict(kind=proof['kind'],task=task,sha256=digest))
            store._put(attempt,'delivery_receipt',task,dict(kind=proof['kind'],sha256=digest))
    finally:
        store.close()
    return digest


def previous_receipt(release,task):
    from coordination_store import CoordinationStore
    store=CoordinationStore('/opt/data/governance/coordination.db')
    try:
        reference=store.get(release['attempt'],'delivery_receipt',task)
        if not reference:
            return None
        return EvidenceStore('/opt/data/governance/evidence',release['attempt']).load(reference['sha256'])
    finally:
        store.close()
