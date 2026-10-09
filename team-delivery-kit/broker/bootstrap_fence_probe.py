"""Fixed offline preparation probe. Never runs agent code or product tests."""
import hashlib
import json
import os
from pathlib import Path
import seed_workspace
import workspace_lockdown


def main():
    selection=json.loads(os.environ['REVISION_SEED_JSON'])
    frozen=json.loads(Path('/previous/manifest.json').read_text())
    contract=json.loads(Path('/base/contract.json').read_text())
    scope=sorted(selection['product_sha256'])
    work=Path('/evidence-work')
    for name,expected in frozen['files'].items():
        if name not in contract['files']:continue
        path=work/name
        if path.is_symlink() or not path.is_file():raise ValueError('actual workspace file missing')
        if hashlib.sha256(path.read_bytes()).hexdigest()!=expected['sha256']:
            raise ValueError('actual workspace diverged from frozen candidate')
    conflicts=[name for name in scope if (work/name).stat().st_size>32768]
    if not conflicts:raise ValueError('measured legacy product size conflict required')
    seed_workspace.main()
    hashes={name:hashlib.sha256((Path('/workspace')/name).read_bytes()).hexdigest()
            for name in contract['test_files'] if (Path('/workspace')/name).is_file()}
    workspace_lockdown.lockdown('/base','/workspace',scope)
    for name,value in hashes.items():
        path=Path('/workspace')/name
        if (hashlib.sha256(path.read_bytes()).hexdigest()!=value
                or path.stat().st_mode&0o777!=0o444):raise ValueError('frozen test fence drift')
    for name,value in selection['product_sha256'].items():
        path=Path('/workspace')/name
        if (hashlib.sha256(path.read_bytes()).hexdigest()!=value
                or path.stat().st_mode&0o777!=0o666):raise ValueError('product fence drift')
    print(json.dumps(dict(operation='preprompt_product_fence_probe_v1',
        manifest_sha256=selection['manifest_sha256'],product_sha256=selection['product_sha256'],
        test_sha256=selection['test_sha256'],scope=scope,legacy_size_conflicts=conflicts,
        actual_workspace_unchanged=True,frozen_tests_intact=True,test_files=len(hashes),
        lockdown_sha256=hashlib.sha256(Path('/workspace_lockdown.py').read_bytes()).hexdigest(),
        product_limit=workspace_lockdown.MAX_FILE_BYTES,delivery_approval=False,tests_executed=False),sort_keys=True))


if __name__=='__main__':main()
