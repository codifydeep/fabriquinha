"""Real disposable Docker canary; does not register/approve an installed policy."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from docker_grouping import args
from generic_harness_calibration import digest,validate_receipt
from test_generic_harness_calibration import GenericCalibrationTests


def main(image):
    if not re.fullmatch('sha256:[a-f0-9]{64}',image):raise ValueError('pinned offline canary image required')
    fixture=GenericCalibrationTests();fixture.setUp()
    try:
        test_path=fixture.candidate/'tests/test_contract.py'
        test=test_path.read_text().replace(' def test_existing_behavior(self):\n',
            ' def test_existing_behavior(self):\n'
            '  self.assertFalse(Path("/var/run/docker.sock").exists())\n'
            '  for path in (Path("/candidate/app/value.txt"),Path("/controls/positive.txt"),Path("/policy/policy.json")):\n'
            '   with self.assertRaises(OSError): path.write_text("forbidden")\n')
        manifest,files=fixture.snapshot(fixture.candidate,{
            'tests/test_contract.py':test,'app/value.txt':'broken'})
        fixture.policy['candidate_manifest_sha256']=manifest
        fixture.policy['test_sha256']['tests/test_contract.py']=files['tests/test_contract.py']['sha256']
        policy_root=fixture.candidate.parent/'policy';policy_root.mkdir()
        (policy_root/'policy.json').write_text(json.dumps(fixture.policy,sort_keys=True))
        for root in (fixture.candidate,fixture.controls,policy_root):
            os.chmod(root,0o755)
            for path in root.rglob('*'):os.chmod(path,0o755 if path.is_dir() else 0o444)
        command=['docker','run','--rm','--network','none','--read-only','--user','10000:10000',
            '--cap-drop','ALL','--security-opt','no-new-privileges','--memory','512m','--cpus','1',
            '--pids-limit','96','--tmpfs','/tmp:rw,nosuid,nodev,size=64m,mode=1777',
            *args('generic-calibration-canary','delivery-kit-port2'),
            '-e','PYTHONDONTWRITEBYTECODE=1']
        for root,target in ((fixture.candidate,'/candidate'),(fixture.controls,'/controls'),(policy_root,'/policy')):
            command+=['--mount','type=bind,src='+str(root)+',dst='+target+',readonly']
        command+=['--entrypoint','python',image,'/generic_harness_calibration.py',
            '/candidate','/controls','/policy/policy.json',digest(fixture.policy)]
        completed=subprocess.run(command,text=True,capture_output=True,timeout=60)
        if completed.returncode:raise ValueError('real offline calibration canary rejected')
        receipt=validate_receipt(json.loads(completed.stdout),fixture.policy,digest(fixture.policy))
        print(json.dumps(dict(status='passed',image=image,positive_tests=receipt['positive']['tests'],
            negative_assertion_failures=sum(x['failures'] for x in receipt['negative_controls'].values()),
            candidate_readonly=True,controls_readonly=True,policy_readonly=True,
            network='none',socket_mounted=False,installed_policy_approved=False,
            product_green=False,red_approved=False,delivery_approval=False)))
    finally:
        # Restore fixture modes solely so TemporaryDirectory can remove its own
        # files. No Docker resource is removed through a prefix or global prune.
        for root in (fixture.candidate,fixture.controls,fixture.candidate.parent/'policy'):
            if root.exists():
                for path in root.rglob('*'):os.chmod(path,0o755 if path.is_dir() else 0o644)
        fixture.doCleanups()


if __name__=='__main__':main(sys.argv[1])
