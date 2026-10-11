"""Actual immutable-bundle writer qualification with synthetic data only."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import uuid

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from docker_grouping import args as group_args
from generic_harness_calibration import digest
from generic_calibration_v2_canary import archive
from generic_calibration_bundle_writer import inventory
from test_generic_harness_calibration_v2 import MultiPathCalibrationTests


def main(image):
    if not re.fullmatch('sha256:[a-f0-9]{64}',image):raise ValueError('exact image required')
    source=Path(__file__).resolve().parents[1]
    cycle=str(uuid.uuid4());root=source/'.local-port2'/'backups'/('writer-v2-canary-'+cycle)
    root.mkdir(mode=0o700)
    fixture=MultiPathCalibrationTests();fixture.setUp()
    try:
        p=fixture.policy
        record=dict(operation='generic_calibration_proposal_bundle_v1',policy=p,policy_sha256=digest(p),
            controls=fixture.control_files,controls_manifest=inventory(fixture.control_files),
            execution_authorized=False,delivery_approval=False)
        hashes={name:hashlib.sha256((source/name).read_bytes()).hexdigest() for name in (
            'generic_calibration_bundle_writer.py','calibration_policy_adapter.py',
            'generic_harness_calibration_v2.py','generic_harness_calibration.py','r3_snapshot_probe.py')}
        code='''import hashlib,json,os,sys
from pathlib import Path
sys.path.insert(0,"/")
from generic_calibration_bundle_writer import write
from generic_harness_calibration import digest
data=json.load(sys.stdin);record=data["record"]
for name,expected in data["hashes"].items():
 assert hashlib.sha256(Path("/",name).read_bytes()).hexdigest()==expected
assert not Path("/var/run/docker.sock").exists()
assert not any(k in os.environ for k in ("OPENROUTER_API_KEY","GH_TOKEN","GITHUB_TOKEN","TELEGRAM_BOT_TOKEN"))
receipt=write("/controls","/policy",record,digest(record))
assert receipt==write("/controls","/policy",record,digest(record))
for name,content in record["controls"].items():assert Path("/controls",name).read_text()==content
try:write("/controls","/policy",record,"0"*64)
except ValueError:pass
else:raise RuntimeError("stale bundle accepted")
assert all(receipt[k] is False for k in ("tests_executed","execution_authorized","delivery_approval"))
print(json.dumps({"receipt":receipt,"source_hashes_verified":True,"idempotent":True,"stale_digest_rejected":True,"socket_absent":True,"credentials_absent":True}))
'''
        name='delivery-kit-port2-writer-v2-canary-'+cycle
        argv=['docker','run','--rm','-i','--name',name,*group_args('calibration-writer-v2-canary','delivery-kit-port2'),
            '--label','delivery-kit.canary='+cycle,'--network','none','--read-only','--user','10000:10000',
            '--cap-drop','ALL','--security-opt','no-new-privileges','--memory','256m','--cpus','1','--pids-limit','64',
            '--tmpfs','/controls:rw,nosuid,nodev,size=16m,mode=1777',
            '--tmpfs','/policy:rw,nosuid,nodev,size=16m,mode=1777',
            '--tmpfs','/tmp:rw,nosuid,nodev,size=16m,mode=1777',
            '--entrypoint','python',image,'-B','-c',code]
        archive(root,'intent.json',dict(image=image,container=name,argv=argv,record=record,hashes=hashes,paid_calls=0))
        result=subprocess.run(argv,input=json.dumps(dict(record=record,hashes=hashes)),capture_output=True,text=True,timeout=60)
        archive(root,'observed.json',dict(exit_code=result.returncode,stdout=result.stdout,stderr=result.stderr))
        if result.returncode:raise ValueError('writer canary failed; observe exact container, never replay')
        observed=json.loads(result.stdout);archive(root,'qualified.json',observed)
        print(json.dumps(dict(passed=True,image=image,source_hashes_verified=True,
            idempotent=True,stale_digest_rejected=True,native_approval=False,product_state_changed=False)))
    finally:fixture.doCleanups()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--image',required=True)
    main(parser.parse_args().image)
