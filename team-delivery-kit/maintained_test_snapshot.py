"""Project an approved immutable test artifact, without rewriting any byte.

This fixed offline operation prepares inputs only. It never executes delivered
code, imports tests, creates Red evidence or accepts an agent command.
"""
import hashlib
import json
import os
from pathlib import Path
import tempfile

from generic_harness_calibration import require
from portable_contract import validate
from r3_snapshot_probe import probe
try:from test_first_protocol import prepare_red, _regular
except ImportError:from broker.test_first_protocol import prepare_red, _regular


def project(base, source, target, selection):
    base,source,target=map(Path,(base,source,target))
    require(set(selection)=={'base_manifest_sha256','candidate_manifest_sha256','test_sha256'})
    require(hashlib.sha256(_regular(base,'manifest.json')).hexdigest()==selection['base_manifest_sha256'])
    probe(source,selection['candidate_manifest_sha256'])
    contract=validate(json.loads(_regular(base,'contract.json')))
    original=json.loads(_regular(base,'manifest.json'))
    require(set(original)=={'base_sha','files'})
    baseline=set(original['files'])-{'contract.json'}
    tests=set(selection['test_sha256'])
    require(tests and not tests & baseline and tests==set(contract['test_files'])-baseline)
    files=json.loads(_regular(source,'manifest.json'))['files']
    require(set(files)==baseline|tests)
    # Validate the entire source before materializing even a partial projection.
    for name in sorted(files):
        raw=_regular(source,name)
        require((source/name).stat().st_nlink==1)
        if name in baseline:
            require(raw==_regular(base,name) and hashlib.sha256(raw).hexdigest()==original['files'][name])
        else:require(hashlib.sha256(raw).hexdigest()==selection['test_sha256'][name])
    require(not target.is_symlink() and not any(p.is_symlink() for p in target.rglob('*')))
    with tempfile.TemporaryDirectory() as directory:
        workspace=Path(directory)
        for name in sorted(files):
            dest=workspace/name;dest.parent.mkdir(parents=True,exist_ok=True)
            dest.write_bytes(_regular(source,name))
        result=prepare_red(base,workspace,target,contract,resume=True)
    require(result['manifest_sha256']==selection['candidate_manifest_sha256']
        and result['test_sha256']==selection['test_sha256'])
    probe(source,selection['candidate_manifest_sha256']);probe(target,selection['candidate_manifest_sha256'])
    for path in target.rglob('*'):
        if path.is_file():
            require(path.stat().st_nlink==1)
            with path.open('rb') as stream:os.fsync(stream.fileno())
    return result


if __name__=='__main__':
    print(json.dumps(project('/base','/source','/snapshot',json.loads(os.environ['MAINTAINED_TEST_SELECTION'])),sort_keys=True))
