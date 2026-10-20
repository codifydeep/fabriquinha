"""Operator-only, no-model qualification of explicit review-fact queries.

Queries are NOT extracted from or attributed to a previous prose review. This
does not reopen it, grant another review, or alter any workflow state.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import uuid
from controller_maintenance_cli import arguments
from docker_grouping import args as grouping
import literal_review_claims as facts

PROGRAM='''import broker as b,json,sys,literal_maintenance_effects as e,literal_maintenance_workflow as f
b.TOKEN=(b.STATE/"token").read_text()
key,namespace=sys.argv[1:];f.require(b.PREFIX==namespace)
with b.db() as c:
 row=c.execute("SELECT config,state FROM literal_maintenance_workflows WHERE source_task=?",(key,)).fetchone();f.require(row)
 cfg,s=map(json.loads,row)
 f.require(not c.execute("SELECT 1 FROM leases WHERE status IN (?,?,?,?)",("creating","starting","running","closing")).fetchone())
fx=e.Effects(b.handoff_context());fx.verify(cfg);f.authenticate_reconsideration(cfg,s,fx)
r=s["reconsideration"]
shadow=dict(s,wakeup_id=s["reconsideration_wakeup"],marker=s["reconsideration_marker"])
f.require(fx.decision(cfg,shadow,"reconsider",{"id":r["task_id"]})==r)
f.require(s["stage"]=="blocked" and s["category"]=="maintenance_feedback_reconsideration_rejected")
sources={
 "original":{"volume":cfg["source"]["candidate_volume"],"manifest":cfg["source"]["prepared"]["manifest_sha256"]},
 "seed":{"volume":cfg["feedback_strategy"]["policy"]["previous_volume"],"manifest":cfg["feedback_strategy"]["policy"]["previous_manifest_sha256"]},
 "candidate":{"volume":s["snapshot"]["volume"],"manifest":s["inspection"]["candidate_manifest_sha256"]}}
print(json.dumps(dict(path=cfg["test_path"],review_task=r["task_id"],review_receipt_sha256=f.digest(r),sources=sources)))
'''


def save(path,value):
    with os.fdopen(os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'w') as out:
        json.dump(value,out,sort_keys=True);out.flush();os.fsync(out.fileno())


def qualify(namespace,workflow,image,claims):
    require=facts.require
    target=arguments(namespace,'status','')[4]
    require(str(uuid.UUID(workflow))==workflow and re.fullmatch('sha256:[a-f0-9]{64}',image))
    require(isinstance(claims,list) and 1<=len(claims)<=3 and len(json.dumps(claims))<=8192
        and all(isinstance(v,dict) and set(v)==facts.FIELDS for v in claims))
    labels=json.loads(subprocess.check_output(['docker','inspect','--format','{{json .Config.Labels}}',target],text=True))
    require(labels.get('com.docker.compose.project')==namespace and labels.get('com.docker.compose.service')=='execution-broker')
    source=json.loads(subprocess.check_output(['docker','exec','-w','/',target,'python','-c',PROGRAM,workflow,namespace],text=True,timeout=60))
    common=['docker','run','--rm',*grouping('literal-review-claim-qualification',namespace),'--network','none','--read-only',
        '--cap-drop','ALL','--security-opt','no-new-privileges','--user','10000:10000','--memory','256m','--cpus','1','--pids-limit','32']
    helper_sha=hashlib.sha256(Path(facts.__file__).read_bytes()).hexdigest()
    probe=subprocess.check_output([*common,'--entrypoint','python',image,'-c',
        'import hashlib;print(hashlib.sha256(open("/literal_review_claims.py","rb").read()).hexdigest())'],text=True,timeout=30).strip()
    require(probe==helper_sha)
    intent=dict(operation='qualify_literal_review_claims_v1',namespace=namespace,workflow=workflow,source=source,image=image,
        helper_sha256=helper_sha,qualifier_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        claims=claims,claims_origin='explicit_controller_diagnostic_queries_not_parsed_review_prose')
    key=hashlib.sha256(json.dumps(intent,sort_keys=True).encode()).hexdigest()
    private=Path(__file__).resolve().parent/('.local-'+namespace.removeprefix('delivery-kit-'))
    root=private/'probes'/('literal-review-claims-'+key)
    require(not private.is_symlink() and not root.parent.is_symlink() and not root.is_symlink())
    if root.exists():
        require((root/'receipt.json').is_file() and not (root/'receipt.json').is_symlink())  # Unknown completion is observed, never blindly retried.
        receipt=json.loads((root/'receipt.json').read_text());require(receipt['identity']==intent);return key,receipt
    root.mkdir(mode=0o700,parents=True);save(root/'intent.json',intent)
    cmd=list(common)
    for name,v in source['sources'].items():cmd+=['-v',v['volume']+':/'+name+':ro']
    cmd +=[image,'/literal_review_claims.py','/original','/seed','/candidate',
        json.dumps({k:v['manifest'] for k,v in source['sources'].items()}),source['path'],json.dumps(claims)]
    completed=subprocess.run(cmd,text=True,capture_output=True)
    receipt=dict(identity=intent,exit_code=completed.returncode,output_sha256=hashlib.sha256(completed.stdout.encode()).hexdigest())
    if completed.returncode:receipt.update(output=completed.stdout,stderr=completed.stderr)
    else:
        result=json.loads(completed.stdout);require(result['operation']=='literal_review_claim_facts_v1'
            and result['source_manifests']=={k:v['manifest'] for k,v in source['sources'].items()}
            and [v['claim'] for v in result['claims']]==claims and result['model_calls']==0
            and all(result[k] is False for k in ('source_reset','delivery_approval','review_override',
                'semantic_approval','author_retry_authorized','historical_tdd_red')))
        receipt['facts']=result
    save(root/'receipt.json',receipt);return key,receipt


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('namespace','workflow','image','claims-json'):p.add_argument('--'+name,required=True)
    a=p.parse_args();claims=json.loads(a.claims_json,object_pairs_hook=facts.unique)
    key,r=qualify(a.namespace,a.workflow,a.image,claims)
    print(json.dumps(dict(key=key,exit_code=r['exit_code'],model_calls=0,review_overridden=False,
        supported=[v['supported'] for v in r.get('facts',{}).get('claims',[])]),sort_keys=True))
    raise SystemExit(r['exit_code'])


if __name__=='__main__':main()
