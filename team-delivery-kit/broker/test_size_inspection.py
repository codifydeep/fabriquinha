"""Fixed read-only measurement of hash-bound historical NEW tests."""
import hashlib
import json
import os
from pathlib import Path
from portable_contract import safe_path


def inspect(root,selection):
    root=Path(root)
    def read(name,limit):
        safe_path(name);path=root/name
        if (path.is_symlink() or not path.is_file() or path.stat().st_size>limit
                or any(p.is_symlink() for p in list(path.parents)[:len(Path(name).parts)-1])):
            raise ValueError('unsafe measured artifact')
        return path.read_bytes()
    encoded=read('manifest.json',32768)
    digest=hashlib.sha256(encoded).hexdigest()
    if digest!=selection['manifest_sha256']:raise ValueError('measurement manifest drift')
    manifest=json.loads(encoded)['files'];files={}
    for name,expected in selection['test_sha256'].items():
        data=read(name,65536);actual=hashlib.sha256(data).hexdigest()
        facts={'sha256':actual,'bytes':len(data)}
        if expected!=actual or manifest.get(name)!=facts:raise ValueError('measurement test drift')
        files[name]=facts
    return {'manifest_sha256':digest,'files':files}


if __name__=='__main__':
    print(json.dumps(inspect('/red',json.loads(os.environ['SELECTION_JSON']))))
