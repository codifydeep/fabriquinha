"""Controller-owned content-addressed deliveries. Never mount writable in workers."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile


def sha(data):
    return hashlib.sha256(data).hexdigest()


def identity(value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',value):
        raise ValueError('invalid delivery identity')
    return value


class DeliveryStore:
    def __init__(self,root):
        self.root=Path(root)
        self.root.mkdir(parents=True,exist_ok=True,mode=0o700)

    def capture(self,workspace,*,attempt,task,author,run):
        workspace=Path(workspace).resolve(strict=True)
        if not workspace.is_dir(): raise ValueError('workspace required')
        scope=self.root/identity(attempt)/identity(task)
        scope.mkdir(parents=True,exist_ok=True)
        files={}
        total=0
        for file in sorted(workspace.rglob('*')):
            relative=file.relative_to(workspace).as_posix()
            if '__pycache__' in file.parts: continue
            if file.is_symlink(): raise ValueError('symlink not allowed: '+relative)
            if file.is_dir(): continue
            if not file.is_file(): raise ValueError('regular files only')
            if file.stat().st_size>16*1024*1024: raise ValueError('file exceeds limit')
            data=file.read_bytes()
            total+=len(data)
            if total>64*1024*1024 or len(files)>=1000: raise ValueError('delivery exceeds limit')
            files[relative]=data
        if not files: raise ValueError('empty delivery')
        manifest=dict(attempt=identity(attempt),task=identity(task),author=identity(author),
            run=int(run),files={name:dict(sha256=sha(data),bytes=len(data)) for name,data in files.items()})
        raw=json.dumps(manifest,sort_keys=True,separators=(',',':')).encode()
        revision=sha(raw)
        destination=scope/revision
        if destination.exists():
            self.load(attempt,task,revision)
            return revision
        temporary=Path(tempfile.mkdtemp(prefix='.pending-',dir=scope))
        try:
            for name,data in files.items():
                path=temporary/'files'/name
                path.parent.mkdir(parents=True,exist_ok=True)
                with path.open('xb') as stream:
                    stream.write(data); stream.flush(); os.fsync(stream.fileno())
                path.chmod(0o444)
                if (workspace/name).is_symlink() or (workspace/name).read_bytes()!=data:
                    raise ValueError('workspace changed while freezing: '+name)
            with (temporary/'manifest.json').open('xb') as stream:
                stream.write(raw); stream.flush(); os.fsync(stream.fileno())
            os.rename(temporary,destination)
            fd=os.open(scope,os.O_RDONLY)
            try: os.fsync(fd)
            finally: os.close(fd)
        finally:
            if temporary.exists(): shutil.rmtree(temporary)
        self.load(attempt,task,revision)
        return revision

    def path(self,attempt,task,revision):
        if not re.fullmatch(r'[0-9a-f]{64}',revision): raise ValueError('invalid revision')
        return self.root/identity(attempt)/identity(task)/revision

    def load(self,attempt,task,revision):
        path=self.path(attempt,task,revision)
        raw=(path/'manifest.json').read_bytes()
        if sha(raw)!=revision: raise ValueError('manifest digest mismatch')
        manifest=json.loads(raw)
        if manifest['attempt']!=attempt or manifest['task']!=task:
            raise ValueError('delivery identity mismatch')
        for name,expected in manifest['files'].items():
            file=path/'files'/name
            if file.is_symlink(): raise ValueError('snapshot symlink')
            data=file.read_bytes()
            if sha(data)!=expected['sha256'] or len(data)!=expected['bytes']:
                raise ValueError('snapshot corrupt: '+name)
        return manifest

    def differences(self,attempt,task,revision,workspace):
        manifest=self.load(attempt,task,revision)
        differences=[]
        for name,expected in manifest['files'].items():
            path=Path(workspace)/name
            current=sha(path.read_bytes()) if path.is_file() and not path.is_symlink() else None
            if current!=expected['sha256']:
                differences.append(dict(category='delivery_changed',file=name,
                    expected=expected['sha256'],actual=current,next_action='request_changes'))
        return differences
