"""Synthetic real-Docker qualification, not native role or product evidence."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from docker_grouping import args as group_args
from generic_harness_calibration import digest
from generic_harness_calibration_v2 import validate_receipt
from test_generic_harness_calibration_v2 import MultiPathCalibrationTests


def archive(root,name,value):
    with os.fdopen(os.open(root/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'w') as file:
        json.dump(value,file,sort_keys=True)


def main(image):
    if not re.fullmatch('sha256:[a-f0-9]{64}',image):raise ValueError('exact image required')
    cycle=str(uuid.uuid4());root=Path(__file__).resolve().parents[1]/'.local-port2'/'backups'/('v2-canary-'+cycle)
    root.mkdir(mode=0o700)
    archive(root,'identity.json',dict(image=image,cycle=cycle,paid_calls=0,native_approval=False))
    fixture=MultiPathCalibrationTests();fixture.setUp()
    try:
        policy_root=fixture.candidate.parent/'policy';policy_root.mkdir()
        (policy_root/'policy.json').write_text(json.dumps(fixture.policy))
        synthetic=root/'synthetic';synthetic.mkdir(mode=0o700)
        for role,path in (('candidate',fixture.candidate),('controls',fixture.controls),('policy',policy_root)):
            shutil.copytree(path,synthetic/role)
        expected=digest(fixture.policy)
        code='''import os,json,subprocess,sys
from pathlib import Path
sys.path.insert(0,"/")
from generic_harness_calibration_v2 import run
for name in ("/candidate/tests/test_ui.py","/candidate/app/app.js","/candidate/app/index.html","/controls/js-positive.js","/policy/policy.json"):
 try:
  with open(name,"r+b"):pass
 except OSError as error:
  assert error.errno in (13,30)
 else:raise RuntimeError("snapshot writable")
assert not Path("/var/run/docker.sock").exists()
assert not any(k in os.environ for k in ("OPENROUTER_API_KEY","GH_TOKEN","GITHUB_TOKEN","TELEGRAM_BOT_TOKEN"))
assert subprocess.run(["node","-e","process.stdout.write(String(1+1))"],capture_output=True,text=True,check=True,timeout=5).stdout=="2"
p=json.loads(Path("/policy/policy.json").read_text())
r=run("/candidate","/controls",p,sys.argv[1])
print(json.dumps({"receipt":r,"readonly":True,"socket_absent":True,"credentials_absent":True,"node_runtime":True}))
'''
        name='delivery-kit-port2-v2-canary-'+cycle
        argv=['docker','run','--rm','--name',name,*group_args('calibration-v2-canary','delivery-kit-port2'),
            '--label','delivery-kit.canary='+cycle,'--network','none','--read-only','--user','10000:10000',
            '--cap-drop','ALL','--security-opt','no-new-privileges','--memory','512m','--cpus','1',
            '--pids-limit','96','--tmpfs','/tmp:rw,nosuid,nodev,size=64m,mode=1777']
        for target in ('candidate','controls','policy'):
            path=synthetic/target
            argv+=['--mount','type=bind,src='+str(path)+',dst=/'+target+',readonly']
        argv += ['--entrypoint','python',image,'-B','-c',code,expected]
        archive(root,'intent.json',dict(container=name,argv=argv,policy=fixture.policy,policy_sha256=expected))
        result=subprocess.run(argv,capture_output=True,text=True,timeout=60)
        archive(root,'observed.json',dict(exit_code=result.returncode,stdout=result.stdout,stderr=result.stderr))
        if result.returncode:raise ValueError('canary failed; observe exact container, never replay')
        observed=json.loads(result.stdout);validate_receipt(observed['receipt'],fixture.policy,expected)
        archive(root,'qualified.json',observed)
        print(json.dumps(dict(passed=True,image=image,positive_tests=observed['receipt']['positive']['tests'],
            negative_controls=len(observed['receipt']['negative_controls']),readonly=observed['readonly'],
            socket_absent=observed['socket_absent'],credentials_absent=observed['credentials_absent'],
            node_runtime=observed['node_runtime'],native_approval=False,product_state_changed=False)))
    finally:fixture.doCleanups()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--image',required=True)
    main(parser.parse_args().image)
