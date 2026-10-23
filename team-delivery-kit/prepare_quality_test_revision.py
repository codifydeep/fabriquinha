"""Prepare a qualified rejection handoff under the exact sealed maintenance.

No task, wakeup, model, grant, approval or history reset. The resumed coordinator
owns subsequent dispatch. Repeated observations return the same durable record.
"""
import argparse
import json
import subprocess
from quality_candidate_authority import Authority
from qualify_quality_red_observer import require_idle
from recover_quality_review import arguments

PROGRAM='''import sys,json
sys.path.insert(0,"/")
import broker as b,quality_test_revision as revision
p=json.loads(sys.stdin.read(4097))
c,s=revision.register(b,p["source"],maintenance_operation=p["operation"])
assert c["bootstrap_maintenance_operation"]==p["operation"]
print(json.dumps(dict(stage=s["stage"],source_task=c["source_task"],issue_id=c["issue_id"],
 context_sha256=revision.quality.digest(c),manifest_sha256=c["seed"]["manifest_sha256"],
 tests_approved=False,delivery_approval=False,model_calls=0),sort_keys=True))
'''


def prepare(namespace,image,source,operation):
    # Reuse strict syntax validation only; no recovery registration is invoked.
    arguments(namespace,image,source,source,'0'*64,operation)
    authority=Authority(namespace,image);about=authority.about()
    if about['maintenance'] is not True or about['v2_enabled'] is not False:raise ValueError('disabled sealed controller required')
    held,_=require_idle(namespace)
    if held['operation_id']!=operation:raise ValueError('exact sealed operation required')
    result=subprocess.run(['docker','exec','-i','-w','/',authority.identity,'python','-c',PROGRAM],
        input=json.dumps(dict(source=source,operation=operation)),capture_output=True,text=True,timeout=120)
    if result.returncode or len(result.stdout.encode())>16384 or authority.inspect_controller()!=authority.identity:
        raise ValueError('revision preparation rejected; inspect preserved state, never grant permission manually')
    return json.loads(result.stdout)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('namespace','image','source','operation'):p.add_argument('--'+key,required=True)
    a=p.parse_args();print(json.dumps(prepare(a.namespace,a.image,a.source,a.operation),sort_keys=True))
