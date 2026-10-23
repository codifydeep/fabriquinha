"""Operator-only changed-adapter recovery of one pre-admission review failure.

No worker, model, author replay, test mutation or approval. After a lost reply,
--observe reads the same durable recovery. The resumed coordinator owns the
later one-shot dispatch, not this CLI.
"""
import argparse
import json
import re
import subprocess
import uuid
from quality_candidate_authority import Authority
from quality_git_candidate import require
from qualify_quality_red_observer import require_idle

PROGRAM='''import sys,json
sys.path.insert(0,"/")
import broker as b,quality_review_recovery as recovery
p=json.loads(sys.stdin.read(4097))
if sys.argv[1]=="observe":
 value=recovery.load(b,p["source_task"])
 if value is not None:
  assert value["request"]==p
else:value=recovery.register(b,p["source_task"],p["failed_task"],p["adapter_sha256"],p["maintenance_operation"])
keys=("operation","source_task","failed_task","new_marker","manifest_sha256","plan_sha256","red_sha256","tests_approved","delivery_approval","model_calls")
print(json.dumps(dict(stage="not_observed" if value is None else "recovery_registered",receipt={k:value[k] for k in keys} if value else None,delivery_approval=False),sort_keys=True))
'''


def arguments(namespace,image,source,failed,adapter,operation):
    require(re.fullmatch('delivery-kit-[a-z0-9-]{1,48}',namespace) and re.fullmatch('sha256:[a-f0-9]{64}',image))
    for value in (source,failed,operation):require(str(uuid.UUID(value))==value)
    require(re.fullmatch('[a-f0-9]{64}',adapter))
    return dict(source_task=source,failed_task=failed,adapter_sha256=adapter,maintenance_operation=operation)


def run(namespace,image,source,failed,adapter,operation,*,observe=False):
    payload=arguments(namespace,image,source,failed,adapter,operation)
    authority=Authority(namespace,image);about=authority.about()
    if not observe:
        require(about['maintenance'] is True)
        maintenance,_=require_idle(namespace);require(maintenance['operation_id']==operation)
    try:
        result=subprocess.run(['docker','exec','-i','-w','/',authority.identity,'python','-c',PROGRAM,
            'observe' if observe else 'register'],input=json.dumps(payload),capture_output=True,text=True,timeout=120)
    except subprocess.TimeoutExpired:
        return dict(stage='observation_timeout',source_task=source,next_action='observe same recovery; no new task or capability',delivery_approval=False)
    require(result.returncode==0 and len(result.stdout.encode())<=16384 and authority.inspect_controller()==authority.identity)
    value=json.loads(result.stdout);require(value['delivery_approval'] is False)
    if value['receipt'] is not None:
        receipt=value['receipt'];require(value['stage']=='recovery_registered' and receipt['source_task']==source
            and receipt['failed_task']==failed and receipt['tests_approved'] is False and receipt['delivery_approval'] is False
            and receipt['model_calls']==0)
    else:require(observe and value['stage']=='not_observed')
    return value


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('namespace','image','source','failed-task','adapter-sha','operation'):p.add_argument('--'+key,required=True)
    p.add_argument('--observe',action='store_true');a=p.parse_args()
    print(json.dumps(run(a.namespace,a.image,a.source,a.failed_task,a.adapter_sha,a.operation,observe=a.observe),sort_keys=True))
