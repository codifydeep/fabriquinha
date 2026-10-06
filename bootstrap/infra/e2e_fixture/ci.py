"""Executed from the trusted PR BASE, never from the proposed head."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import runpy

def git(*args): return subprocess.check_output(['git',*args])
base=os.environ['BASE_SHA']; head=os.environ['HEAD_SHA']
allowed={'rehearsal/app.py','rehearsal/test_user.py','rehearsal/NOTES.md'}
changed=set(git('diff','--name-only',base,head).decode().splitlines())
assert changed and changed<=allowed, 'untrusted workflow/infrastructure/test modification'
with tempfile.TemporaryDirectory(dir=os.getcwd(),prefix='.e2e-ci-') as tmp:
    root=Path(tmp)
    root.chmod(0o755)
    for name in ['policy.py','test_regression.py','test_acceptance.py']:
        (root/name).write_bytes(git('show',base+':rehearsal/'+name))
    validate=runpy.run_path(str(root/'policy.py'))['validate']
    for name in ['app.py','test_user.py','NOTES.md']:
        result=subprocess.run(['git','show',head+':rehearsal/'+name],capture_output=True)
        if result.returncode:
            assert name=='NOTES.md'; continue
        validate(name,result.stdout.decode()); (root/name).write_bytes(result.stdout)
    result=subprocess.run(['docker','run','--rm','--network','none','--read-only','--cap-drop','ALL',
        '--security-opt','no-new-privileges','--pids-limit','64','--memory','128m','--cpus','1',
        '--user','65534:65534','--mount','type=bind,src='+tmp+',dst=/delivery,readonly',
        '--workdir','/delivery','--entrypoint','/usr/bin/python3',os.environ['TEST_IMAGE'],
        '-B','-m','unittest','discover','-v'])
    raise SystemExit(result.returncode)
