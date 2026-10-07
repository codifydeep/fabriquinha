"""Read and hash a frozen delivery. Never import or execute delivered code."""
import hashlib
import json
from pathlib import Path,PurePosixPath
import re


def probe(root,expected):
    root=Path(root)
    if not re.fullmatch('[a-f0-9]{64}',expected) or root.is_symlink() or not root.is_dir():
        raise ValueError('exact snapshot root and manifest hash required')
    manifest=root/'manifest.json'
    if manifest.is_symlink() or not manifest.is_file() or manifest.stat().st_size>524288:
        raise ValueError('bounded regular manifest required')
    raw=manifest.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=expected:raise ValueError('frozen manifest hash mismatch')
    value=json.loads(raw)
    if set(value)!={'files'} or not isinstance(value['files'],dict) or not 1<=len(value['files'])<=2048:
        raise ValueError('bounded frozen file inventory required')
    actual=set();total=0;directories=0
    for path in root.rglob('*'):
        if path.is_symlink():raise ValueError('snapshot symlink forbidden')
        if path.is_file():
            actual.add(path.relative_to(root).as_posix())
            if len(actual)>2049:raise ValueError('snapshot inventory too large')
        elif path.is_dir():
            directories+=1
            if directories>4096:raise ValueError('snapshot directory inventory too large')
        else:raise ValueError('snapshot special file forbidden')
    if actual!=set(value['files'])|{'manifest.json'}:raise ValueError('snapshot file inventory drift')
    for name,record in value['files'].items():
        relative=PurePosixPath(name)
        if (relative.is_absolute() or relative.as_posix()!=name or '..' in relative.parts
                or not isinstance(record,dict) or set(record)!={'bytes','sha256'}
                or type(record['bytes']) is not int or not 0<=record['bytes']<=33554432
                or not re.fullmatch('[a-f0-9]{64}',str(record['sha256']))):
            raise ValueError('exact bounded frozen entry required')
        path=root/name;size=path.stat().st_size;total+=size
        if size!=record['bytes'] or total>134217728:raise ValueError('snapshot byte inventory drift')
        hashed=hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda:stream.read(1048576),b''):hashed.update(chunk)
        if hashed.hexdigest()!=record['sha256']:raise ValueError('snapshot file hash mismatch')
    return dict(status='passed',observation='snapshot_hashes_match',manifest_sha256=expected,
                file_count=len(value['files']),total_bytes=total)
