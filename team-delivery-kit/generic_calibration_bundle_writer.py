"""Fixed offline materializer. Never execute supplied code or overwrite files.

Run only in a controller-owned disposable job. Candidate/previous snapshots
are not mounted here; only newly owned controls/policy targets may be writable.
Volume ownership, durable Docker intents and independent approvals belong to
the controller, not to this writer's nonauthorizing receipt.
"""
import hashlib
import json
from pathlib import Path
import sys

from generic_harness_calibration import digest,relative,require,validate_policy
from r3_snapshot_probe import probe


def inventory(files):
    return json.dumps({'files':{name:dict(bytes=len(content.encode()),
        sha256=hashlib.sha256(content.encode()).hexdigest()) for name,content in files.items()}},sort_keys=True)


def expected_files(record,expected):
    fields={'operation','policy','policy_sha256','controls','controls_manifest','execution_authorized','delivery_approval'}
    require(isinstance(record,dict) and fields<=set(record)
        and set(record)<=fields|{'producer','candidate_volume'} and digest(record)==expected
        and record.get('operation')=='generic_calibration_proposal_bundle_v1'
        and record.get('execution_authorized') is False and record.get('delivery_approval') is False)
    p=validate_policy(record['policy'],record['policy_sha256']);controls=record['controls']
    require(isinstance(controls,dict) and 1<=len(controls)<=288)
    total=0
    for name,content in controls.items():
        relative(name);require(name!='manifest.json' and isinstance(content,str))
        size=len(content.encode());total+=size
        require(0<size<=65536 and total<=524288)
    fixtures={m['positive_fixture'] for m in p['modules']}|{n['fixture'] for n in p['negatives']}
    require(set(controls)==fixtures)
    control_manifest=inventory(controls)
    require(record['controls_manifest']==control_manifest
        and hashlib.sha256(control_manifest.encode()).hexdigest()==p['controls_manifest_sha256'])
    policies={'policy.json':json.dumps(p,sort_keys=True)+'\n'}
    return dict(controls={**controls,'manifest.json':control_manifest},
        policy={**policies,'manifest.json':inventory(policies)})


def inspect_target(root,files):
    require(not root.is_symlink() and root.is_dir())
    for path in root.rglob('*'):
        require(not path.is_symlink())
        name=path.relative_to(root).as_posix()
        if path.is_dir():require(any(n.startswith(name+'/') for n in files))
        else:
            require(path.is_file() and name in files and path.stat().st_size==len(files[name].encode()))
            require(path.read_bytes()==files[name].encode())
    # Reject a path that would need a file to be replaced by a directory.
    for name in files:
        relative(name)
        for parent in (root/name).parents:
            if parent==root:break
            require(not parent.exists() or parent.is_dir())


def write(controls,policy,record,expected):
    files=expected_files(record,expected)
    roots={'controls':Path(controls),'policy':Path(policy)}
    require(roots['controls'].resolve()!=roots['policy'].resolve())
    # Check BOTH targets before the first write. Interrupted exact writes can
    # resume; foreign/tampered entries are retained, never repaired in place.
    for role,root in roots.items():inspect_target(root,files[role])
    for role,root in roots.items():
        for name,content in files[role].items():
            path=root/name;path.parent.mkdir(parents=True,exist_ok=True)
            if not path.exists():
                with path.open('xb') as stream:stream.write(content.encode())
            path.chmod(0o444)
        inspect_target(root,files[role])
    policy_manifest=hashlib.sha256(files['policy']['manifest.json'].encode()).hexdigest()
    probe(roots['controls'],record['policy']['controls_manifest_sha256'])
    probe(roots['policy'],policy_manifest)
    return dict(operation='generic_calibration_bundle_materialized_v1',bundle_sha256=expected,
        policy_sha256=record['policy_sha256'],controls_manifest_sha256=record['policy']['controls_manifest_sha256'],
        policy_manifest_sha256=policy_manifest,tests_executed=False,execution_authorized=False,delivery_approval=False)


if __name__=='__main__':
    try:
        require(len(sys.argv)==5)
        source=Path(sys.argv[3]);require(not source.is_symlink() and source.is_file() and source.stat().st_size<=1048576)
        print(json.dumps(write(sys.argv[1],sys.argv[2],json.loads(source.read_text()),sys.argv[4]),sort_keys=True))
    except Exception as error:
        print(json.dumps(dict(status='rejected',category=type(error).__name__,tests_executed=False,
            execution_authorized=False,delivery_approval=False)));sys.exit(1)
