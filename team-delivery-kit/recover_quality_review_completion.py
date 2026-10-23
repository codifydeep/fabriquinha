"""Fixed operator registration of a qualified changed-condition review successor.

Reads verified install/restore and zero-model worker qualification archives.
Never creates a task, grant, worker or model call; dispatch remains with the
coordinator after activation and maintenance release. --observe reads the same
request after an uncertain reply instead of resending registration.
"""
import argparse
import json
from pathlib import Path
import subprocess
from quality_candidate_authority import Authority
from quality_git_candidate import require,canonical
from qualify_quality_red_observer import require_idle
from recover_quality_review import arguments
from migrate_quality_candidate_pin import read
from qualify_quality_review_stop import GUARDS,sha,validate_report

ROOT=Path(__file__).resolve().parent
PROGRAM='''import sys,json
sys.path.insert(0,"/")
import broker as b,quality_review_completion_recovery as recovery
p=json.loads(sys.stdin.read(65537))
if sys.argv[1]=="observe":
 values=[v for v in recovery.records(b,p["source_task"]) if v["previous_task"]==p["previous_task"]]
 assert len(values)<=1
 value=values[0] if values else None
 if value:assert value["request"]==p
else:value=recovery.register(b,p["source_task"],p["previous_task"],p["maintenance_operation"],qualified=p["qualification"],installation=p["installation"],transport=p.get("transport"))
keys=("operation","source_task","previous_task","previous_request","new_marker","manifest_sha256","condition_sha256","ordinal","incident_closed","tests_approved","delivery_approval","model_calls")
print(json.dumps(dict(stage="not_observed" if value is None else "completion_recovery_registered",receipt={k:value[k] for k in keys} if value else None,delivery_approval=False),sort_keys=True))
'''


def qualification(namespace,identity,operation):
    canonical(identity)
    archive=ROOT/('.local-'+namespace.removeprefix('delivery-kit-'))/'backups'/('quality-review-stop-'+identity)
    state=json.loads(read(archive/'state.json'));output=json.loads(read(archive/'output.json'))
    require(state['stage']=='qualified' and output['returncode']==0)
    value=state['receipt'];guards={key:sha((ROOT/path).read_bytes()) for key,path in GUARDS.items()}
    require(value['operation']=='qualified_review_stop_worker_v1' and value['namespace']==namespace
        and value['qualification_id']==identity and value['maintenance_operation']==operation
        and value['guards']==guards and value['worker_image']==state['identity']['image']
        and value['container_retired'] is True and value['model_calls']==0 and value['tests_approved'] is False
        and value['delivery_approval'] is False and value['output_sha256']==sha(output['stdout'].encode())
        and value['command_sha256']==state['command_sha256']
        and value['script_sha256']==sha((ROOT/'tests/quality_review_stop_canary.py').read_bytes()))
    validate_report(value['report'],guards)
    reports=[]
    for line in output['stdout'].splitlines():
        try:report=json.loads(line)
        except ValueError:continue
        if isinstance(report,dict) and report.get('operation')=='real_hermes_review_stop_loop_canary_v1':reports.append(report)
    require(reports==[value['report']])
    return value


def run(namespace,image,source,previous,operation,install_operation,qualification_id,*,observe=False,proxy_install_operation=None):
    # Reuse strict fixed-target syntax; this is not the zero-ACP recovery guard.
    arguments(namespace,image,source,previous,'0'*64,operation)
    canonical(install_operation)
    authority=Authority(namespace,image);about=authority.about()
    archive=ROOT/('.local-'+namespace.removeprefix('delivery-kit-'))/'backups'/('quality-preview-install-'+install_operation)
    state=json.loads(read(archive/'state.json'));before=json.loads(read(archive/'before.json'))
    backup=json.loads(read(archive/'backup-receipt.json'));receipt=state['receipt']
    require(state['stage']=='installed_disabled' and state['operation']==install_operation and state['image']==image
        and state['maintenance_operation']==operation and receipt['previous_image']==before['Image']
        and before['Image']!=image and backup['backup_id']==install_operation
        and backup['backup_integrity']=='ok' and backup['restore_integrity']=='ok'
        and receipt['namespace']==namespace and receipt['image']==image and receipt['maintenance_sealed'] is True
        and receipt['data_mounts_preserved'] is True and backup['operation_id']==operation and backup['source_reset'] is False)
    installation=dict(install_operation=install_operation,previous_image=before['Image'],current_image=image,
        previous_container=before['Id'],current_container=receipt['container_id'])
    qualified=qualification(namespace,qualification_id,operation)
    if not observe:
        require(about['maintenance'] is True and about['v2_enabled'] is False and about['implementation_enabled'] is False)
        held,_=require_idle(namespace);require(held['operation_id']==operation and authority.identity==installation['current_container'])
    payload=dict(source_task=source,previous_task=previous,maintenance_operation=operation,
        qualification=qualified,installation=installation)
    if proxy_install_operation is not None:
        canonical(proxy_install_operation)
        program='''import sys,json
sys.path.insert(0,"/")
import broker as b,quality_test_review as review,quality_review_completion_recovery as recovery
source,previous=sys.argv[1:]
_,state=review.load(b,source)
if state.get("review_task")==previous:request=state["request_id"]
else:
 records=[r for r in recovery.records(b,source) if r["previous_task"]==previous]
 assert len(records)==1
 request=records[0]["previous_request"]
print(json.dumps(dict(request_id=request)))'''
        found=subprocess.run(['docker','exec',authority.identity,'python','-c',program,source,previous],
            capture_output=True,text=True,timeout=20)
        require(found.returncode==0 and len(found.stdout)<=4096 and authority.inspect_controller()==authority.identity)
        request=json.loads(found.stdout)['request_id'];canonical(request)
        from review_capacity_evidence import load
        payload['transport']=load(namespace,proxy_install_operation,operation,request)
    raw=json.dumps(payload);require(len(raw.encode())<=65536)
    try:
        result=subprocess.run(['docker','exec','-i','-w','/',authority.identity,'python','-c',PROGRAM,
            'observe' if observe else 'register'],input=raw,capture_output=True,text=True,timeout=120)
    except subprocess.TimeoutExpired:
        return dict(stage='observation_timeout',next_action='observe same recovery; no manual task assignment',delivery_approval=False)
    require(result.returncode==0 and len(result.stdout.encode())<=16384 and authority.inspect_controller()==authority.identity)
    value=json.loads(result.stdout);require(value['delivery_approval'] is False)
    if value['receipt'] is not None:
        record=value['receipt'];require(record['source_task']==source and record['previous_task']==previous
            and record['tests_approved'] is False and record['delivery_approval'] is False
            and record['model_calls']==0 and record['incident_closed'] is False)
    else:require(observe)
    return value


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('namespace','image','source','previous-task','operation','install-operation','qualification'):
        parser.add_argument('--'+key,required=True)
    parser.add_argument('--proxy-install-operation',help='Exact qualified proxy upgrade for a failed capacity-bound review')
    parser.add_argument('--observe',action='store_true');args=parser.parse_args()
    print(json.dumps(run(args.namespace,args.image,args.source,args.previous_task,args.operation,
        args.install_operation,args.qualification,observe=args.observe,proxy_install_operation=args.proxy_install_operation),sort_keys=True))
