"""Fixed operator-only native v2 enrollment; no launch, approval or legacy grants.

The private payload contains a plan, portable contract and maintenance identity.
Its bytes are pinned before validation. Enrollment itself is immutable and
idempotent in the controller transaction. An observation timeout is not a failure
or permission to create a different issue/run: use --observe on the same payload.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
from broker import quality_lifecycle_enrollment as enrollment
from quality_candidate_authority import Authority
from quality_git_candidate import require
from qualify_quality_red_observer import require_idle

PROGRAM='''import sys,json
sys.path.insert(0,"/")
import broker as b,quality_lifecycle_enrollment as enrollment
payload=json.loads(sys.stdin.read(65537))
plan,contract=enrollment.request(payload)
if sys.argv[1]=="observe":
 with b.db() as con:
  result=enrollment.lookup(con,plan["issue_id"])
  if result is not None:
   stored=json.loads(con.execute("SELECT config FROM quality_lifecycle_enrollments WHERE issue_id=?",(plan["issue_id"],)).fetchone()[0])
   if stored!=payload:raise ValueError("immutable enrollment differs")
else:
 result=enrollment.enroll(b,payload)
print(json.dumps(dict(stage="not_observed" if result is None else "enrolled",receipt=result,delivery_approval=False),sort_keys=True))
'''


def load(path,pin):
    path=Path(path)
    require(path.is_absolute() and path.resolve()==path and not path.is_symlink())
    info=path.stat()
    require(stat.S_ISREG(info.st_mode) and info.st_uid==os.getuid() and info.st_nlink==1
        and not info.st_mode&0o077 and 0<info.st_size<=65536
        and isinstance(pin,str) and re.fullmatch('[a-f0-9]{64}',pin))
    raw=path.read_bytes();require(hashlib.sha256(raw).hexdigest()==pin)
    def pairs(values):
        require(len({k for k,_ in values})==len(values));return dict(values)
    def invalid(_):raise ValueError('finite JSON required')
    value=json.loads(raw,object_pairs_hook=pairs,parse_constant=invalid)
    enrollment.request(value)
    return value


class Effects:
    def authority(self,namespace,image):return Authority(namespace,image)
    def idle(self,namespace):return require_idle(namespace)
    def invoke(self,identity,payload,observe):
        return subprocess.run(['docker','exec','-i','-w','/',identity,'python','-c',PROGRAM,
            'observe' if observe else 'enroll'],input=json.dumps(payload),capture_output=True,
            text=True,timeout=120)


def run(namespace,image,path,pin,*,observe=False,effects=None):
    require(isinstance(namespace,str) and re.fullmatch('delivery-kit-[a-z0-9-]{1,48}',namespace)
        and isinstance(image,str) and re.fullmatch('sha256:[a-f0-9]{64}',image)
        and type(observe) is bool)
    payload=load(path,pin);plan,contract=enrollment.request(payload)
    require(len(json.dumps(payload).encode())<=65536)
    fx=effects or Effects();authority=fx.authority(namespace,image);about=authority.about()
    require(about['namespace']==namespace)
    if not observe:
        require(about['maintenance'] is True and about['v2_enabled'] is False and about['implementation_enabled'] is False)
        maintenance,_=fx.idle(namespace)
        require(maintenance['operation_id']==payload['maintenance_operation'])
    try:result=fx.invoke(authority.identity,payload,observe)
    except subprocess.TimeoutExpired:
        return dict(stage='observation_timeout',issue_id=plan['issue_id'],run_id=plan['run_id'],
            next_action='observe the same immutable payload; never create a replacement run',delivery_approval=False,model_calls=0)
    require(result.returncode==0 and len(result.stdout.encode())<=65536)
    require(authority.inspect_controller()==authority.identity)
    value=json.loads(result.stdout)
    require(set(value)=={'stage','receipt','delivery_approval'} and value['delivery_approval'] is False)
    receipt=value['receipt']
    if receipt is None:require(observe and value['stage']=='not_observed')
    else:
        require(value['stage']=='enrolled' and receipt['operation']=='quality_lifecycle_enrollment_v2'
            and receipt['namespace']==namespace and receipt['issue_id']==plan['issue_id']
            and receipt['run_id']==plan['run_id'] and receipt['plan_sha256']==enrollment.policy.digest(plan)
            and receipt['contract_sha256']==plan['contract_sha256']
            and all(receipt[k]==plan[k] for k in ('base_sha','author','reviewer'))
            and receipt['repository']==contract['repository']
            and receipt['maintenance_operation']==payload['maintenance_operation']
            and receipt['stage']=='enrolled_pending_adapter'
            and all(receipt[k] is False for k in ('execution_authorized','merge_authorized',
                'delivery_approval','baseline_bytes_verified')))
    return {**value,'model_calls':0}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('namespace','image','payload','pin'):parser.add_argument('--'+key,required=True)
    parser.add_argument('--observe',action='store_true');args=parser.parse_args()
    print(json.dumps(run(args.namespace,args.image,args.payload,args.pin,observe=args.observe),sort_keys=True))
