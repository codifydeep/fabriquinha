"""Source-bound isolated diagnostic; cannot submit controls or advance a delivery.

Runs once per immutable source/probe image/script. Private intents survive an
uncertain Docker acknowledgment. No retries, pruning or worker API is provided.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
import uuid
from docker_grouping import args
from generic_harness_calibration import digest,require

ROOT=Path(__file__).resolve().parent
QUERY='''import sys,json,os;sys.path.insert(0,"/")
import broker as b,calibration_objection_runtime as o,controller_maintenance as m
with b.db() as c:
 row=c.execute("SELECT config,state FROM calibration_objections WHERE issue_id=?",(sys.argv[1],)).fetchone();assert row
 cfg,s=map(json.loads,row);fx=o.Effects(b);fx.verify(cfg);fx.verify_decision(cfg,s)
 assert s['stage']=='blocked' and s.get('category')=='experiment_plan_rejected'
 for phase,key in (('design','proposal'),('review','review')):
  receipt=s['experiment'][key];task=fx.plans.task(receipt['task_id'],receipt['agent_id'])
  assert fx.experiment_decision(cfg,s,task,phase)==receipt
 assert s['experiment']['review']['value']['action']=='retain_technical_hold'
 assert c.execute("SELECT count(*) FROM leases WHERE status IN (?,?,?,?)",('creating','starting','running','closing')).fetchone()[0]==0
 assert not m.native_active(b)
 print(json.dumps(dict(source=cfg['source'],hold=s['experiment']['review'],owner=b.OWNER,prefix=b.PREFIX,
  image=os.environ['BROKER_GENERIC_CALIBRATION_NODE_IMAGE'])))
'''


def docker(*command):return subprocess.check_output(['docker',*command],timeout=30)


def private_json(path,value):
    with os.fdopen(os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'w') as f:
        json.dump(value,f,sort_keys=True);f.flush();os.fsync(f.fileno())


def private_bytes(path,value):
    with os.fdopen(os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'wb') as f:
        f.write(value);f.flush();os.fsync(f.fileno())


def validate_receipt(receipt,identity,c):
    require(set(receipt)=={'operation','identity','facts','delivery_approval','author_restart','calibration_approved'}
        and receipt['operation']=='qualified_frozen_harness_diagnostic_v1' and receipt['identity']==identity
        and all(receipt[k] is False for k in ('delivery_approval','author_restart','calibration_approved')))
    facts=receipt['facts']
    require(facts['operation']=='frozen_harness_diagnostic_v1' and facts['candidate_manifest_sha256']==c['prepared']['manifest_sha256']
        and facts['test_sha256']==c['prepared']['test_sha256'] and facts['snapshot_unchanged'] is True
        and facts['product_bytes']=='original_frozen_candidate' and type(facts['model_calls']) is int and facts['model_calls']==0
        and set(facts['modules'])==set(c['test_files'])
        and all(facts[k] is False for k in ('full_regression_suite_executed','calibration_approved','red_approved',
            'product_green','author_retry_authorized','execution_authorized','delivery_approval')))
    for path,module in facts['modules'].items():
        require(set(module)=={'tests','outcomes','failures','errors','skipped','expected_failures','unexpected_successes'}
            and all(type(module[k]) is int and module[k]>=0 for k in module if k!='outcomes')
            and module['tests']==len(c['prepared']['test_methods'][path]) and len(module['outcomes'])==module['tests']
            and sorted(v['test'].split('.',1)[1] for v in module['outcomes'])==sorted(c['prepared']['test_methods'][path]))
    return receipt


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--issue',required=True);options=parser.parse_args()
    require(str(uuid.UUID(options.issue))==options.issue)
    controller='delivery-kit-port2-execution-broker-1'
    labels=json.loads(docker('inspect','--format','{{json .Config.Labels}}',controller))
    require(labels.get('com.docker.compose.project')=='delivery-kit-port2' and labels.get('com.docker.compose.service')=='execution-broker')
    context=json.loads(docker('exec',controller,'python','-c',QUERY,options.issue));c=context['source']
    require(context['prefix']=='delivery-kit-port2' and bool(re.fullmatch('sha256:[a-f0-9]{64}',context['image'])))
    volume=json.loads(docker('volume','inspect',c['candidate_volume']))[0]
    require(volume['Labels'].get('delivery-kit.owner')==context['owner']
        and volume['Labels'].get('delivery-kit.test-first-task')==c['author_task'])
    script=ROOT/'calibration_frozen_harness_probe.py';script_sha=hashlib.sha256(script.read_bytes()).hexdigest()
    identity=dict(source_sha256=digest(c),hold_sha256=digest(context['hold']),script_sha256=script_sha,image=context['image'])
    key=digest(identity);folder=ROOT/'.local-port2'/'probes'/('frozen-harness-'+key)
    folder.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    if folder.exists():
        if (folder/'receipt.json').is_file():
            print(json.dumps(validate_receipt(json.loads((folder/'receipt.json').read_text()),identity,c)));return
        raise ValueError('existing diagnostic intent: inspect its exact Docker handle; never restart')
    folder.mkdir(mode=0o700);name='delivery-kit-port2-frozen-harness-'+key[:24]
    command=['docker','run','--rm','--name',name,*args('frozen-harness-diagnostic','delivery-kit-port2'),
        '--label','delivery-kit.owner='+context['owner'],'--network','none','--read-only','--user','10000:10000',
        '--cap-drop','ALL','--security-opt','no-new-privileges','--memory','512m','--cpus','1','--pids-limit','64',
        '--tmpfs','/tmp:rw,nosuid,nodev,size=64m,mode=1777','-v',c['candidate_volume']+':/candidate:ro',
        '-v',str(script)+':/frozen-harness-probe.py:ro','--entrypoint','python',context['image'],
        '-B','/frozen-harness-probe.py','/candidate',c['prepared']['manifest_sha256'],
        json.dumps(c['prepared']['test_sha256'],sort_keys=True),json.dumps(c['prepared']['test_methods'],sort_keys=True)]
    private_json(folder/'intent.json',dict(identity=identity,name=name,source=c,started=time.time(),delivery_approval=False))
    try:result=subprocess.run(command,capture_output=True,timeout=240)
    except subprocess.TimeoutExpired:
        private_json(folder/'observation.json',dict(category='docker_ack_uncertain',handle=name,delivery_approval=False));raise
    private_bytes(folder/'stdout.log',result.stdout);private_bytes(folder/'stderr.log',result.stderr)
    private_json(folder/'observation.json',dict(exit_code=result.returncode,stdout_sha256=hashlib.sha256(result.stdout).hexdigest(),
        stderr_sha256=hashlib.sha256(result.stderr).hexdigest(),delivery_approval=False))
    require(result.returncode==0 and 0<len(result.stdout)<=65536 and not result.stderr)
    facts=json.loads(result.stdout)
    receipt=dict(operation='qualified_frozen_harness_diagnostic_v1',identity=identity,facts=facts,
        delivery_approval=False,author_restart=False,calibration_approved=False)
    validate_receipt(receipt,identity,c)
    private_json(folder/'receipt.json',receipt);print(json.dumps(receipt,sort_keys=True))


if __name__=='__main__':main()
