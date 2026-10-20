"""Recover only a sole, exact stopped Compose controller. Never stops it itself."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import uuid
from docker_grouping import args
from generic_harness_calibration import digest,require
from qualify_frozen_harness import private_json,private_bytes

ROOT=Path(__file__).resolve().parent


def docker(*cmd):return subprocess.check_output(['docker',*cmd],text=True,timeout=30)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('namespace','operation','container','image'):p.add_argument('--'+name,required=True)
    a=p.parse_args();require(bool(re.fullmatch('delivery-kit-[a-z0-9-]{1,48}',a.namespace))
        and str(uuid.UUID(a.operation))==a.operation and bool(re.fullmatch('[a-f0-9]{64}',a.container))
        and bool(re.fullmatch('sha256:[a-f0-9]{64}',a.image)))
    ids=docker('ps','-aq','--no-trunc','--filter','label=com.docker.compose.project='+a.namespace,
        '--filter','label=com.docker.compose.service=execution-broker').splitlines();require(ids==[a.container])
    def stopped():
        labels=json.loads(docker('inspect','--format','{{json .Config.Labels}}',a.container))
        state=json.loads(docker('inspect','--format','{{json .State}}',a.container))
        require(labels.get('com.docker.compose.project')==a.namespace and labels.get('com.docker.compose.service')=='execution-broker'
            and state['Running'] is False and state['Pid']==0 and state['Status']=='exited')
        return state
    state=stopped();mounts=json.loads(docker('inspect','--format','{{json .Mounts}}',a.container))
    selected=[m for m in mounts if m['Destination']=='/broker-state'];require(len(selected)==1)
    mount=selected[0];require(mount['Type'] in ('bind','volume'))
    identity=dict(operation_id=a.operation,namespace=a.namespace,container_id=a.container,
        state={k:state[k] for k in ('Running','Pid','Status','StartedAt','FinishedAt')})
    folder=ROOT/'.local-port2/backups'/('stopped-cycle-'+a.operation)
    require(not folder.exists());folder.mkdir(mode=0o700,parents=True)
    script=ROOT/'broker/stopped_cycle_recovery.py';name=a.namespace+'-stopped-cycle-'+a.operation[:8]
    private_json(folder/'intent.json',dict(identity=identity,image=a.image,script_sha256=hashlib.sha256(script.read_bytes()).hexdigest(),name=name))
    stopped()  # Revalidate immediately before granting the one administrative mount.
    source=mount['Name'] if mount['Type']=='volume' else mount['Source']
    command=['docker','run','--rm','--name',name,*args('stopped-cycle-recovery',a.namespace),
        '--network','none','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges','--memory','256m','--pids-limit','32',
        '--user','0:0','--mount','type='+mount['Type']+',source='+source+',target=/state',
        '-v',str(script)+':/recover.py:ro','--entrypoint','python',a.image,'-B','/recover.py',json.dumps(identity,sort_keys=True)]
    try:result=subprocess.run(command,capture_output=True,timeout=240)
    except subprocess.TimeoutExpired:
        private_json(folder/'observation.json',dict(category='ack_uncertain',handle=name,delivery_approval=False));raise
    private_bytes(folder/'stdout.log',result.stdout);private_bytes(folder/'stderr.log',result.stderr)
    require(result.returncode==0 and not result.stderr);receipt=json.loads(result.stdout)
    require(receipt['identity']==identity and receipt['cycle_completed'] is False and receipt['delivery_approval'] is False)
    private_json(folder/'receipt.json',receipt);print(json.dumps(receipt,sort_keys=True))


if __name__=='__main__':main()
