"""One source-bound diagnostic for a completed native technical hold. No retries.

No worker starts, source resets, approvals or policy changes. Existing intent
means inspect the same Docker handle, never issue another run automatically.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import uuid
from docker_grouping import args
from generic_harness_calibration import digest,require
from qualify_frozen_harness import private_json,private_bytes,docker
from calibration_harness_protocol_probe import FALSE_FLAGS

ROOT=Path(__file__).resolve().parent
QUERY='''import sys,json,os;sys.path.insert(0,"/")
import broker as b,controller_maintenance as m,calibration_controls_diagnostic as d
with b.db() as c:
 row=c.execute("SELECT config,state FROM calibration_control_experiments WHERE issue_id=?",(sys.argv[1],)).fetchone();assert row
 cfg,s=map(json.loads,row);assert m.current(c)['stage']=='sealed'
 assert s['stage']=='blocked' and s['category']=='diagnostic_objection_review_hold'
 assert c.execute("SELECT count(*) FROM leases WHERE status IN (?,?,?,?)",('creating','starting','running','closing')).fetchone()[0]==0
assert not m.native_active(b)
fx=d.Effects(b);fx.verify(cfg);p=s['objection']['producer']
assert fx.collect(cfg,{**s,'wakeup_id':p['wakeup_id']},{'id':p['task_id']})==s['objection']
decision=s['objection_decision'];assert fx.decision(cfg,s,{'id':decision['task_id']})==decision
assert decision['value']['action']=='retain_technical_hold'
print(json.dumps(dict(source=cfg['source'],hold=decision,owner=b.OWNER,prefix=b.PREFIX,image=os.environ['BROKER_GENERIC_CALIBRATION_CONTROLS_IMAGE'])))
'''


def validate(receipt,identity,source):
    require(set(receipt)=={'operation','identity','facts',*FALSE_FLAGS}
        and receipt['operation']=='qualified_frozen_harness_protocol_counterexample_v1' and receipt['identity']==identity
        and all(receipt[k] is False for k in FALSE_FLAGS))
    f=receipt['facts'];require(f['operation']=='frozen_harness_protocol_counterexample_v1'
        and f['candidate_manifest_sha256']==source['prepared']['manifest_sha256']
        and f['test_sha256']==source['prepared']['test_sha256'] and f['probe_sha256']==identity['script_sha256']
        and f['snapshot_unchanged'] is True and f['frozen_node_harness_executed'] is True
        and type(f['model_calls']) is int and f['model_calls']==0 and all(f[k] is False for k in FALSE_FLAGS)
        and all(f['measurements'][k] is False for k in FALSE_FLAGS))
    return receipt


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--issue',required=True);opt=p.parse_args()
    require(str(uuid.UUID(opt.issue))==opt.issue);controller='delivery-kit-port2-execution-broker-1'
    labels=json.loads(docker('inspect','--format','{{json .Config.Labels}}',controller))
    require(labels.get('com.docker.compose.project')=='delivery-kit-port2'
        and labels.get('com.docker.compose.service')=='execution-broker')
    context=json.loads(docker('exec',controller,'python','-c',QUERY,opt.issue));c=context['source']
    require(context['prefix']=='delivery-kit-port2' and c['test_files']==['tests/test_feedback_latest_ui.py'])
    volume=json.loads(docker('volume','inspect',c['candidate_volume']))[0]
    require(volume['Labels'].get('delivery-kit.owner')==context['owner']
        and volume['Labels'].get('delivery-kit.test-first-task')==c['author_task'])
    script=ROOT/'calibration_harness_protocol_probe.py'
    identity=dict(source_sha256=digest(c),hold_sha256=digest(context['hold']),
        script_sha256=hashlib.sha256(script.read_bytes()).hexdigest(),image=context['image'])
    key=digest(identity);folder=ROOT/'.local-port2'/'probes'/('harness-protocol-'+key);name='delivery-kit-port2-harness-protocol-'+key[:24]
    folder.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    if folder.exists():
        if (folder/'receipt.json').is_file():
            print(json.dumps(validate(json.loads((folder/'receipt.json').read_text()),identity,c),sort_keys=True));return
        raise ValueError('existing protocol-probe intent: inspect exact Docker handle; never replay')
    folder.mkdir(mode=0o700)
    private_json(folder/'intent.json',dict(identity=identity,name=name,source=c,started=time.time(),delivery_approval=False))
    command=['docker','run','--rm','--name',name,*args('frozen-harness-protocol','delivery-kit-port2'),
        '--label','delivery-kit.owner='+context['owner'],'--network','none','--read-only','--user','10000:10000',
        '--cap-drop','ALL','--security-opt','no-new-privileges','--memory','512m','--cpus','1','--pids-limit','64',
        '--tmpfs','/tmp:rw,nosuid,nodev,size=64m,mode=1777','-v',c['candidate_volume']+':/candidate:ro',
        '-v',str(script)+':/harness-protocol-probe.py:ro','--entrypoint','python',context['image'],
        '-B','/harness-protocol-probe.py','/candidate',c['prepared']['manifest_sha256'],c['prepared']['test_sha256'][c['test_files'][0]]]
    try:result=subprocess.run(command,capture_output=True,timeout=130)
    except subprocess.TimeoutExpired:
        private_json(folder/'observation.json',dict(category='docker_ack_uncertain',handle=name,delivery_approval=False));raise
    private_bytes(folder/'stdout.log',result.stdout);private_bytes(folder/'stderr.log',result.stderr)
    private_json(folder/'observation.json',dict(exit_code=result.returncode,stdout_sha256=hashlib.sha256(result.stdout).hexdigest(),
        stderr_sha256=hashlib.sha256(result.stderr).hexdigest(),delivery_approval=False))
    require(result.returncode==0 and 0<len(result.stdout)<=65536 and not result.stderr)
    receipt=dict(operation='qualified_frozen_harness_protocol_counterexample_v1',identity=identity,facts=json.loads(result.stdout),
        **{k:False for k in FALSE_FLAGS})
    validate(receipt,identity,c);private_json(folder/'receipt.json',receipt);print(json.dumps(receipt,sort_keys=True))


if __name__=='__main__':main()
