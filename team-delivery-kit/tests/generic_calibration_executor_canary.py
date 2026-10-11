"""Real isolated-image qualification only; no native approvals or product state.

Each effect is archived before submission. Failure retains exact resources and
is never automatically replayed. Fixtures are synthetic public unit-test data.
"""
import argparse
import copy
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time
import uuid
from types import SimpleNamespace

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from broker import generic_calibration_gate as gate
from generic_harness_calibration import digest,validate_receipt
from generic_calibration_input_probe import run as probe
from docker_grouping import labels
from generic_calibration_materialization_canary import docker,command,stdout
from broker.generic_calibration_materialization import writer_environment
from test_generic_harness_calibration import GenericCalibrationTests

OWNER='calibration-executor-canary'
BASE=Path(__file__).resolve().parents[1]/'.local-port2/backups'
ISOLATION_CODE='''import json,os,subprocess
from pathlib import Path
for name in ("/candidate/tests/test_contract.py","/previous/tests/test_contract.py",
             "/controls/positive.txt","/policy/policy.json"):
 try:
  with open(name,"r+b"):pass
 except PermissionError:pass
 except OSError as e:
  if e.errno!=30:raise
 else:raise RuntimeError("snapshot unexpectedly writable")
assert not Path("/var/run/docker.sock").exists()
assert not any(k in os.environ for k in ("OPENROUTER_API_KEY","GITHUB_TOKEN","GH_TOKEN","TELEGRAM_BOT_TOKEN"))
node=subprocess.run(["node","-e","process.stdout.write(String(1+1))"],capture_output=True,text=True,timeout=5,check=True)
assert node.stdout=="2"
print(json.dumps({"snapshots_readonly":True,"socket_absent":True,"credentials_absent":True,"node_runtime":True}))
'''


def archive(path,value):
    with os.fdopen(os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'w') as stream:
        json.dump(value,stream,sort_keys=True)


def qualify(image,seed_image,resume=None):
    gate.require(all(re.fullmatch('sha256:[a-f0-9]{64}',v) for v in (image,seed_image)))
    prefix='delivery-kit-port2'
    identity=dict(image=image,seed_image=seed_image,owner=OWNER,native_approvals=False,product_state_changed=False)
    if resume:
        root=Path(resume).resolve()
        gate.require(root.parent==BASE.resolve() and root.name.startswith('executor-canary-'))
        cycle=root.name.removeprefix('executor-canary-');gate.require(str(uuid.UUID(cycle))==cycle)
        gate.require(json.loads((root/'identity.json').read_text())==identity)
    else:
        cycle=str(uuid.uuid4());root=BASE/('executor-canary-'+cycle)
        root.mkdir(mode=0o700);archive(root/'identity.json',identity)
    def checkpoint(name,value):
        path=root/name
        if path.exists():gate.require(json.loads(path.read_text())==value)
        else:archive(path,value)
    def create(name,payload,phase):
        intent=root/(phase+'-create-intent.json')
        actual=docker('GET','/containers/'+name+'/json')
        if intent.exists():
            gate.require(json.loads(intent.read_text())==dict(name=name,payload=payload))
            # Lost acknowledgement is observed, never replayed, even if absent.
            gate.require(actual is not None)
        else:
            gate.require(actual is None)
            archive(intent,dict(name=name,payload=payload))
            docker('POST','/containers/create?name='+name,payload)
            actual=docker('GET','/containers/'+name+'/json')
        gate.require(actual is not None)
        return actual
    b=SimpleNamespace(PREFIX=prefix,OWNER=OWNER,GENERIC_CALIBRATION_IMAGE=image,docker=docker)
    env=gate.environment(b,image);seed_env=writer_environment(b,seed_image)
    fixture=GenericCalibrationTests();fixture.setUp()
    try:
        previous=fixture.candidate.parent/'previous';previous.mkdir()
        test='tests/test_contract.py'
        prior_sha,prior_files=fixture.snapshot(previous,{test:(fixture.candidate/test).read_text()})
        policy=fixture.policy;policy_root=fixture.candidate.parent/'policy';policy_root.mkdir()
        (policy_root/'policy.json').write_text(json.dumps(policy,sort_keys=True)+'\n')
        expected_probe=probe(fixture.candidate,previous,fixture.controls,policy,digest(policy),prior_sha)
        sources=dict(candidate=fixture.candidate,previous=previous,controls=fixture.controls,policy=policy_root)
        durable=root/'synthetic'
        if not durable.exists():
            # Legacy migration is safe only before the first copy intent.
            gate.require(not any(root.glob('*-copy-intent.json')))
            durable.mkdir(mode=0o700)
            for role,source in sources.items():shutil.copytree(source,durable/role)
        gate.require(probe(durable/'candidate',durable/'previous',durable/'controls',
            json.loads((durable/'policy/policy.json').read_text()),digest(policy),prior_sha)==expected_probe)
        volumes={role:prefix+'-executor-canary-'+cycle+'-'+role for role in ('candidate','previous','controls','policy')}
        for role,name in volumes.items():
            body=dict(Name=name,Labels={'delivery-kit.owner':OWNER,'delivery-kit.canary':cycle,'delivery-kit.role':role})
            intent=root/(role+'-create-intent.json')
            if intent.exists():checkpoint(intent.name,body)
            else:
                gate.require(docker('GET','/volumes/'+name) is None)
                archive(intent,body);docker('POST','/volumes/create',body)
            actual=docker('GET','/volumes/'+name)
            gate.require(actual and actual.get('Name')==name and actual.get('Labels')==body['Labels'])
        context=dict(candidate_volume=volumes['candidate'],controls_volume=volumes['controls'],
            policy_volume=volumes['policy'],author_task='canary-'+cycle)
        record=dict(policy=policy,policy_sha256=digest(policy),context=context)
        payload=gate.payload(b,record);payload['Image']=seed_image;payload['User']='0:0'
        payload['Env']=seed_env
        payload['Cmd']=['-c','print("seed container must never be started")']
        payload['Labels']={**labels('calibration-canary-seed',prefix),'delivery-kit.owner':OWNER,'delivery-kit.canary':cycle}
        payload['HostConfig']['Mounts']=[dict(Type='volume',Source=name,Target='/'+role,ReadOnly=False)
            for role,name in volumes.items()]
        name=prefix+'-executor-seed-'+cycle
        info=create(name,payload,'seed');gate.require(info['State']['Status']=='created')
        from broker.generic_calibration_materialization import verify as verify_seed
        verify_seed(b,info,payload);seed=info['Id']
        if not (root/'seed-created.json').exists():archive(root/'seed-created.json',info)
        else:gate.require(json.loads((root/'seed-created.json').read_text())['Id']==seed)
        for role in sources:
            body=dict(container_id=seed,volume=volumes[role]);intent=root/(role+'-copy-intent.json')
            done=root/(role+'-copy-done.json')
            if done.exists():checkpoint(done.name,body);checkpoint(intent.name,body);continue
            gate.require(not intent.exists()) # Uncertain copy must not be replayed.
            archive(intent,body);command('cp',str(durable/role)+'/.',seed+':/'+role)
            archive(done,body)
        checkpoint('fixture-policy.json',policy)

        def execute(phase,expected):
            expected=copy.deepcopy(expected)
            expected['Env']=env
            expected['Labels']={**labels('calibration-canary-'+phase,prefix),
                'delivery-kit.owner':OWNER,'delivery-kit.canary':cycle}
            name=prefix+'-executor-'+phase+'-'+cycle
            info=create(name,expected,phase)
            gate.verify_job(b,info,expected);cid=info['Id']
            intent=root/(phase+'-start-intent.json')
            if intent.exists():checkpoint(intent.name,dict(container_id=cid))
            else:
                gate.require(info['State']['Status']=='created')
                archive(intent,dict(container_id=cid));docker('POST','/containers/'+cid+'/start')
            deadline=time.monotonic()+55
            while time.monotonic()<deadline:
                info=docker('GET','/containers/'+cid+'/json')
                gate.verify_job(b,info,expected)
                gate.require(info['Id']==cid)
                if info['State']['Status']=='exited':break
                time.sleep(.5)
            gate.require(info['State']['Status']=='exited' and info['State']['ExitCode']==0)
            raw=stdout(cid);result=json.loads(raw)
            if not (root/(phase+'-result.json')).exists():
                archive(root/(phase+'-result.json'),dict(metadata=info,result=result))
            else:gate.require(json.loads((root/(phase+'-result.json')).read_text())['result']==result)
            return cid,expected,result

        input_payload=gate.payload(b,record)
        input_payload['Cmd']=['/generic_calibration_input_probe.py','/candidate','/previous','/controls',
            '/policy/policy.json',digest(policy),prior_sha]
        input_payload['HostConfig']['Mounts'].append(dict(Type='volume',Source=volumes['previous'],Target='/previous',ReadOnly=True))
        inputs=execute('inputs',input_payload);gate.require(inputs[2]==expected_probe)
        calibration=execute('calibration',gate.payload(b,record));validate_receipt(calibration[2],policy,digest(policy))
        # Re-run the AST/hash probe, proving calibration did not modify its inputs.
        after=execute('after',input_payload);gate.require(after[2]==expected_probe)
        isolation_payload=copy.deepcopy(input_payload);isolation_payload['Cmd']=['-c',ISOLATION_CODE]
        isolation=execute('isolation',isolation_payload)
        gate.require(isolation[2]==dict(snapshots_readonly=True,socket_absent=True,credentials_absent=True,node_runtime=True))
        archive(root/'qualification.json',dict(status='passed',image=image,input_hashes_unchanged=True,
            native_approvals=False,product_state_changed=False,delivery_approval=False))
        for cid,expected,result in (inputs,calibration,after,isolation):
            info=docker('GET','/containers/'+cid+'/json');gate.verify_job(b,info,expected)
            gate.require(info['Id']==cid and info['State']['Status']=='exited'
                and info['Config']['Labels']['delivery-kit.owner']==OWNER)
            archive(root/(cid+'-retire-intent.json'),dict(container_id=cid));command('rm',cid)
        info=docker('GET','/containers/'+seed+'/json');verify_seed(b,info,payload)
        gate.require(info['Id']==seed and info['State']['Status']=='created')
        archive(root/'seed-retire-intent.json',dict(container_id=seed));command('rm',seed)
        return dict(status='passed',archive=str(root),native_approvals=False,
            product_state_changed=False,containers_retired=5,volumes_preserved=4)
    finally:fixture.doCleanups()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('image');parser.add_argument('seed_image')
    parser.add_argument('--resume')
    args=parser.parse_args();print(json.dumps(qualify(args.image,args.seed_image,args.resume),sort_keys=True))
