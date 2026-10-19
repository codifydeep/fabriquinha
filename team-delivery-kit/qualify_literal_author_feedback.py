"""Offline qualification on preserved rejections; never reopens an author task.

Unknown Docker acknowledgments preserve their exact intent/handle. Existing
incomplete intents are observed by the operator, never replayed automatically.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time
import uuid
from docker_grouping import args
from generic_harness_calibration import digest,require
from qualify_frozen_harness import private_json,private_bytes,docker
from literal_author_feedback import FALSE_FLAGS

ROOT=Path(__file__).resolve().parent
QUERY='''import sys,json;sys.path.insert(0,"/")
import broker as b,controller_maintenance as m,literal_maintenance_effects as lane,literal_maintenance_workflow as flow
with b.db() as con:
 row=con.execute("SELECT config,state FROM literal_maintenance_workflows WHERE source_task=?",(sys.argv[1],)).fetchone();assert row
 cfg,s=map(json.loads,row)
 assert s['stage']=='blocked' and s['category']=='maintenance_evidence_replan_rejected' and s['revision']==2
 assert len(s['history'])==3 and s['source_reset'] is False and s['delivery_approval'] is False
 assert con.execute("SELECT count(*) FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone()[0]==0
assert not m.native_active(b)
fx=lane.Effects(b);fx.verify(cfg);flow.authenticate(cfg,s,fx)
candidates=[]
for h in s['history']:
 shadow={**s,**{k:h[k] for k in ('snapshot','inspection','author_task','revision','wakeup_id','marker')}}
 fx.validate_inspection(cfg,shadow,h['inspection']);fx.preserved_submission(cfg,shadow)
 assert fx.decision(cfg,shadow,'review',fx.plans.task(h['review']['task_id'],cfg['reviewer']))==h['review']
 assert h['review']['value']['action']=='reject_test_revision'
 candidates.append(dict(revision=h['revision'],task=h['author_task'],volume=h['snapshot']['volume'],
  sha256=h['inspection']['structure']['candidate_test_sha256'],reports=h['inspection']['reports']))
print(json.dumps(dict(namespace=b.PREFIX,owner=b.OWNER,source_task=cfg['source']['author_task'],
 previous=cfg['source']['candidate_volume'],previous_manifest=cfg['source']['prepared']['manifest_sha256'],
 test_path=cfg['test_path'],candidates=candidates)))
'''


def validate(value,context):
    require(set(value)=={'operation','identity','context_sha256','facts',*FALSE_FLAGS}
        and [c['revision'] for c in context['candidates']]==[0,1,2]
        and value['operation']=='qualified_literal_author_feedback_v1' and value['context_sha256']==digest(context)
        and set(value['facts'])=={str(c['revision']) for c in context['candidates']}
        and all(value[k] is False for k in FALSE_FLAGS))
    for c in context['candidates']:
        f=value['facts'][str(c['revision'])]
        require(f['operation']=='literal_author_feedback_v1' and f['candidate_sha256']==c['sha256']
            and f['previous_manifest_sha256']==context['previous_manifest'] and f['test_path']==context['test_path']
            and f['reports']==c['reports'] and f['checks_passed'] is False and f['failed_fields']==['poll_requests']
            and f['feedback_sha256']==value['identity']['script_sha256']
            and f['capture']['assignment']=='snap.poll_requests = latestCount();'
            and type(f['capture']['literal_line']) is int and f['capture']['literal_line']>0
            and f['candidate_bytes_stable_during_measurement'] is True and f['outside_literal_bytes_preserved'] is True
            and f['non_target_verification']=='not_performed_in_feedback' and type(f['model_calls']) is int
            and f['model_calls']==0 and all(f[k] is False for k in FALSE_FLAGS))
    return value


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--namespace',required=True)
    parser.add_argument('--source-task',required=True);parser.add_argument('--image',required=True);options=parser.parse_args()
    require(bool(re.fullmatch(r'delivery-kit-[a-z0-9-]{1,48}',options.namespace))
        and str(uuid.UUID(options.source_task))==options.source_task
        and bool(re.fullmatch(r'sha256:[a-f0-9]{64}',options.image)))
    controller=options.namespace+'-execution-broker-1'
    labels=json.loads(docker('inspect','--format','{{json .Config.Labels}}',controller))
    require(labels.get('com.docker.compose.project')==options.namespace and labels.get('com.docker.compose.service')=='execution-broker')
    require(json.loads(docker('image','inspect',options.image,'--format','{{json .Id}}'))==options.image)
    context=json.loads(docker('exec',controller,'python','-c',QUERY,options.source_task));require(context['namespace']==options.namespace)
    previous_labels=json.loads(docker('volume','inspect',context['previous'],'--format','{{json .Labels}}'))
    require(previous_labels.get('delivery-kit.owner')==context['owner']
        and previous_labels.get('delivery-kit.test-first-task')==context['source_task'])
    identity=dict(context_sha256=digest(context),image=options.image,
        script_sha256=hashlib.sha256((ROOT/'literal_author_feedback.py').read_bytes()).hexdigest())
    key=digest(identity);folder=ROOT/'.local-port2'/'probes'/('literal-author-feedback-'+key)
    folder.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    if folder.exists():
        if (folder/'receipt.json').is_file():
            value=json.loads((folder/'receipt.json').read_text());require(value['identity']==identity)
            print(json.dumps(validate(value,context),sort_keys=True));return
        raise ValueError('existing feedback qualification intent; observe exact handles, never replay')
    folder.mkdir(mode=0o700);private_json(folder/'intent.json',dict(identity=identity,context=context,started=time.time()))
    facts={}
    for candidate in context['candidates']:
        c=candidate;labels=json.loads(docker('volume','inspect',c['volume'],'--format','{{json .Labels}}'))
        require(labels.get('delivery-kit.owner')==context['owner'] and labels.get('delivery-kit.source-task')==c['task'])
        name=options.namespace+'-author-feedback-'+key[:16]+'-r'+str(c['revision'])
        private_json(folder/('intent-r'+str(c['revision'])+'.json'),dict(name=name,candidate=c,delivery_approval=False))
        command=['docker','run','--rm','--name',name,*args('literal-author-feedback',options.namespace),
            '--label','delivery-kit.owner='+context['owner'],'--network','none','--read-only','--user','10000:10000',
            '--cap-drop','ALL','--security-opt','no-new-privileges','--memory','512m','--cpus','1','--pids-limit','64',
            '--tmpfs','/tmp:rw,nosuid,nodev,size=64m,mode=1777','-v',context['previous']+':/previous:ro',
            '-v',c['volume']+':/candidate:ro','--entrypoint','python',options.image,'-B','/literal_author_feedback.py',
            '/previous','/candidate',context['previous_manifest'],context['test_path'],c['sha256']]
        try:result=subprocess.run(command,capture_output=True,timeout=110)
        except subprocess.TimeoutExpired:
            private_json(folder/'observation.json',dict(category='docker_ack_uncertain',handle=name,delivery_approval=False));raise
        private_bytes(folder/('stdout-r'+str(c['revision'])+'.log'),result.stdout)
        private_bytes(folder/('stderr-r'+str(c['revision'])+'.log'),result.stderr)
        require(result.returncode==0 and 0<len(result.stdout)<=16384 and not result.stderr)
        facts[str(c['revision'])]=json.loads(result.stdout)
    value=dict(operation='qualified_literal_author_feedback_v1',identity=identity,context_sha256=digest(context),
        facts=facts,**{k:False for k in FALSE_FLAGS})
    validate(value,context);private_json(folder/'receipt.json',value);print(json.dumps(value,sort_keys=True))


if __name__=='__main__':main()
