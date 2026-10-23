"""Fixed full Node discovery on an immutable snapshot; no delivery authority.

This executor is not yet wired into native v2 evidence. It exists to preserve
the real repository's Node baseline alongside Python, never to select tests or
reinterpret a baseline failure as a valid new-behavior Red.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from portable_contract import safe_path
from r3_snapshot_probe import probe

REPORTER=Path(__file__).resolve().with_name('quality_node_reporter.mjs')


def require(value):
    if not value:raise ValueError('fixed complete Node baseline evidence required')


def run(root,manifest,tests):
    root=Path(root)
    require(root.is_absolute() and root.resolve()==root and root.is_dir()
        and isinstance(manifest,str) and re.fullmatch('[a-f0-9]{64}',manifest)
        and isinstance(tests,dict) and 1<=len(tests)<=128)
    probe(root,manifest)
    for path,sha in tests.items():
        safe_path(path)
        require(path.endswith(('.js','.mjs','.cjs')) and isinstance(sha,str) and re.fullmatch('[a-f0-9]{64}',sha)
            and not (root/path).is_symlink() and (root/path).is_file()
            and hashlib.sha256((root/path).read_bytes()).hexdigest()==sha)
    binary=shutil.which('node');require(binary is not None and REPORTER.is_file() and not REPORTER.is_symlink())
    # Fixed full discovery, never test-file/name selection or caller commands.
    argv=[binary,'--test','--test-concurrency=1','--test-reporter='+str(REPORTER)]
    env={k:v for k,v in os.environ.items() if k in ('PATH','TMPDIR','TMP','TEMP','LANG','LC_ALL')}
    try:
        result=subprocess.run(argv,cwd=root,env=env,capture_output=True,timeout=120)
        require(len(result.stdout)<=262144 and len(result.stderr)<=262144)
        def unique(pairs):
            require(len({k for k,_ in pairs})==len(pairs));return dict(pairs)
        report=json.loads(result.stdout,object_pairs_hook=unique)
        require(isinstance(report,dict) and set(report)=={'operation','node_version','files','counts',
            'duplicate_summary_fields','captured_output_sha256','captured_output_bytes'}
            and report['operation']=='frozen_node_suite_report_v1'
            and isinstance(report['node_version'],str) and re.fullmatch(r'(22|24)\.[0-9]+\.[0-9]+',report['node_version'])
            and report['duplicate_summary_fields']==[])
        counts=report['counts'];require(isinstance(counts,dict)
            and set(counts)=={'tests','pass','fail','cancelled','skipped','todo'}
            and all(type(v) is int and 0<=v<=100000 for v in counts.values())
            and counts['tests']>0 and counts['tests']==sum(counts[k] for k in ('pass','fail','cancelled','skipped','todo')))
        files=report['files'];require(isinstance(files,list) and len(files)==len(set(files))
            and set(files)=={str(root/p) for p in tests})
        require(isinstance(report['captured_output_sha256'],str) and re.fullmatch('[a-f0-9]{64}',report['captured_output_sha256'])
            and type(report['captured_output_bytes']) is int and report['captured_output_bytes']>=0
            and result.returncode in (0,1))
        passed=result.returncode==0 and counts['pass']==counts['tests'] and all(counts[k]==0 for k in ('fail','cancelled','skipped','todo'))
        return dict(operation='full_node_baseline_observation_v1',status='passed' if passed else 'rejected',
            manifest_sha256=manifest,tests=tests,tests_run=counts['tests'],counts=counts,
            node_version=report['node_version'],exit_code=result.returncode,
            captured_output_sha256=report['captured_output_sha256'],captured_output_bytes=report['captured_output_bytes'],
            stderr_sha256=hashlib.sha256(result.stderr).hexdigest(),snapshot_unchanged=True,
            execution_authorized=False,delivery_approval=False,native_qualification=False)
    finally:probe(root,manifest)


if __name__=='__main__':
    require(len(sys.argv)==1)
    raw=os.environ.get('QUALITY_NODE_BASELINE_JSON','')
    require(0<len(raw.encode())<=65536)
    value=json.loads(raw)
    require(isinstance(value,dict) and set(value)=={'manifest_sha256','tests'})
    print(json.dumps(run(Path('/snapshot'),value['manifest_sha256'],value['tests']),sort_keys=True))
