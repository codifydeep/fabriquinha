"""Fixed read-only comparison of two frozen submissions, never delivery proof."""
import hashlib,json,sys
from pathlib import Path
try:from portable_snapshot_validate import regular_within
except ImportError:from broker.portable_snapshot_validate import regular_within


def inspect(root):
    root=Path(root);raw=regular_within(root,'manifest.json');manifest=json.loads(raw)
    if set(manifest)!={'files'}:raise ValueError('exact frozen manifest required')
    files=manifest['files']
    if not isinstance(files,dict) or not files:raise ValueError('nonempty frozen inventory required')
    actual={str(p.relative_to(root)) for p in root.rglob('*') if p.is_file() or p.is_symlink()}
    if actual!=set(files)|{'manifest.json'}:raise ValueError('snapshot inventory drift')
    for name,record in files.items():
        content=regular_within(root,name)
        if record!={'sha256':hashlib.sha256(content).hexdigest(),'bytes':len(content)}:
            raise ValueError('frozen file drift')
    return raw,files


def compare(previous,current):
    old,files=inspect(previous);new,other=inspect(current)
    if old!=new or files!=other:raise ValueError('submission changed after rejected operation')
    name='tests/test_service_mode_indicator.py'
    return dict(operation='template_admission_preservation_v1',status='passed',
        manifest_sha256=hashlib.sha256(new).hexdigest(),test_sha256=files[name]['sha256'],
        files=len(files),test_bytes=files[name]['bytes'],file_limit_bytes=32768,
        available_growth_bytes=32768-files[name]['bytes'],
        all_files_unchanged=True,delivery_approval=False)


if __name__=='__main__':
    if len(sys.argv)!=3:raise ValueError('two controller-mounted roots required')
    print(json.dumps(compare(sys.argv[1],sys.argv[2]),sort_keys=True))
