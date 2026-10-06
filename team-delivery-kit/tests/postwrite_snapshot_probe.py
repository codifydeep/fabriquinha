"""Read-only integrity qualification of a failed author's partial snapshot."""
import ast
import hashlib
import json
import sys
from pathlib import Path


def main():
    root=Path('/delivery');base=Path('/base');previous=Path('/previous')
    manifest_raw=(root/'manifest.json').read_bytes();files=json.loads(manifest_raw)['files']
    base_files=json.loads((base/'manifest.json').read_text())['files']
    target=sys.argv[1]
    assert target.startswith('tests/test_') and target.endswith('.py')
    assert '..' not in Path(target).parts and not Path(target).is_absolute()
    assert target not in base_files  # Never exclude a pre-existing baseline test.
    for name,record in files.items():
        path=Path(name)
        assert not path.is_absolute() and not any(p in ('','..','.') for p in path.parts)
        f=root/path;assert not f.is_symlink()
        assert not any(p.is_symlink() for p in f.parents if p!=root and root in p.parents)
        raw=f.read_bytes();assert len(raw)==record['bytes']
        assert hashlib.sha256(raw).hexdigest()==record['sha256']
    for name,digest in base_files.items():
        if name=='contract.json':continue
        assert files[name]['sha256']==digest
    current=(root/target).read_bytes();old=(previous/target).read_bytes()
    def methods(raw):
        return sorted(n.name for n in ast.walk(ast.parse(raw))
                      if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name.startswith('test_'))
    before,after=methods(old),methods(current)
    print(json.dumps(dict(operation='postwrite_snapshot_integrity_v1',verified=True,
        baseline_unchanged=True,manifest_sha256=hashlib.sha256(manifest_raw).hexdigest(),
        new_test_sha256=hashlib.sha256(current).hexdigest(),
        previous_test_sha256=hashlib.sha256(old).hexdigest(),
        changed=current!=old,previous_methods=before,current_methods=after,
        methods_preserved=set(before)<=set(after),delivery_approval=False,red_verified=False)))


if __name__=='__main__':main()
