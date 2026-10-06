"""Fresh-process V4 tool/ACP canary using public sources only, no model calls."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile
from offline_validation import ROOT,copy_sources
from docker_grouping import args as docker_group_args


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--image',required=True)
    args=parser.parse_args()
    if not args.image.startswith('sha256:') or len(args.image)!=71:
        raise ValueError('immutable image required')
    with tempfile.TemporaryDirectory(prefix='delivery-kit-public-feedback-') as folder:
        copy_sources(ROOT,Path(folder))
        run=subprocess.run(['docker','run','--rm',
            '--name','delivery-kit-port2-surgical-feedback-qualification',
            *docker_group_args('surgical-feedback',namespace='delivery-kit-port2'),
            '--network','none','--read-only','--cap-drop','ALL',
            '--cap-add','SETUID','--cap-add','SETGID',
            '--security-opt','no-new-privileges','--memory','512m','--cpus','1','--pids-limit','64',
            '--tmpfs','/tmp:size=128m,mode=1777','--tmpfs','/workspace:size=1m,mode=1777',
            '--mount',f'type=bind,source={folder},target=/source,readonly',
            '--workdir','/source','--env','PYTHONDONTWRITEBYTECODE=1',
            '--env','PYTHONPATH=/source:/opt/hermes','--env','HOME=/tmp',
            '--entrypoint','python',args.image,'/source/tests/surgical_line_registry_probe.py'],
            text=True,capture_output=True)
        if run.returncode:
            print(run.stderr[-4000:])
            raise SystemExit(run.returncode)
        receipts=[json.loads(line) for line in run.stdout.splitlines() if line.startswith('{')]
        proof=next(v for v in receipts if v.get('schema')=='surgical-driver-registry-probe-v3')
        proof['worker_image']=args.image
        print(json.dumps(proof,sort_keys=True))


if __name__=='__main__':main()
