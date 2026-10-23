"""Real-repository compatibility diagnostic, NEVER Red/Green or native approval."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from quality_node_baseline import run as node_baseline,require
from r3_snapshot_probe import probe
from test_runner_policy import unacceptable_output


def run(root,manifest,tests):
    root=Path(root);probe(root,manifest)
    try:
        node=node_baseline(root,manifest,tests)
        env={k:v for k,v in os.environ.items() if k in ('PATH','TMPDIR','TMP','TEMP','LANG','LC_ALL')}
        env['PYTHONDONTWRITEBYTECODE']='1'
        result=subprocess.run([sys.executable,'-m','unittest','discover','-s','.','-q'],
            cwd=root,env=env,capture_output=True,timeout=120)
        require(len(result.stdout)+len(result.stderr)<=2097152)
        output=result.stdout+result.stderr;text=output.decode('utf-8','replace')
        matches=re.findall(r'(?m)^Ran ([0-9]+) tests? in ',text)
        python_passed=result.returncode==0 and len(matches)==1 and int(matches[0])>0 and not unacceptable_output(text)
        return dict(operation='python_node_baseline_compatibility_v1',
            status='passed' if python_passed and node['status']=='passed' else 'rejected',
            manifest_sha256=manifest,node=node,python=dict(exit_code=result.returncode,
                tests_run=int(matches[0]) if len(matches)==1 else None,passed=python_passed,
                captured_output_sha256=hashlib.sha256(output).hexdigest(),captured_output_bytes=len(output)),
            snapshot_unchanged=True,native_qualification=False,red_approved=False,green_approved=False,
            execution_authorized=False,delivery_approval=False,model_calls=0)
    finally:probe(root,manifest)


if __name__=='__main__':
    require(len(sys.argv)==1)
    raw=os.environ.get('QUALITY_NODE_BASELINE_JSON','');require(0<len(raw.encode())<=65536)
    value=json.loads(raw);require(isinstance(value,dict) and set(value)=={'manifest_sha256','tests'})
    print(json.dumps(run(Path('/snapshot'),value['manifest_sha256'],value['tests']),sort_keys=True))
