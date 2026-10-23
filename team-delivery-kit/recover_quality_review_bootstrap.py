"""Fixed operator registration of a changed-guard, retired zero-ACP review.

No task, capability, model, test edit, approval or legacy reset. --observe reads
the same receipt after a lost reply. Dispatch belongs to the resumed coordinator.
"""
import argparse
import json
import subprocess
from pathlib import Path
from quality_candidate_authority import Authority
from quality_git_candidate import require
from qualify_quality_red_observer import require_idle
from recover_quality_review import arguments

PROGRAM='''import sys,json
sys.path.insert(0,"/")
import broker as b,quality_review_bootstrap_recovery as recovery
p=json.loads(sys.stdin.read(4097))
if sys.argv[1]=="observe":
 value=recovery.load(b,p["source_task"])
 if value is not None:assert value["request"]==p
else:value=recovery.register(b,p["source_task"],p["failed_task"],p["guard_sha256"],p["maintenance_operation"],installation=p["installation"])
keys=("operation","source_task","failed_task","old_request","new_marker","manifest_sha256","guard_sha256","tests_approved","delivery_approval","model_calls")
print(json.dumps(dict(stage="not_observed" if value is None else "bootstrap_recovery_registered",receipt={k:value[k] for k in keys} if value else None,delivery_approval=False),sort_keys=True))
'''


def run(namespace,image,source,failed,guard,operation,install_operation,*,observe=False):
    arguments(namespace,image,source,failed,guard,operation)
    authority=Authority(namespace,image);about=authority.about()
    from migrate_quality_candidate_pin import read
    from broker.quality_review_bootstrap_recovery import OLD_CONTROLLER_IMAGE
    from quality_git_candidate import canonical
    canonical(install_operation)
    archive=Path(__file__).resolve().parent/('.local-'+namespace.removeprefix('delivery-kit-'))/'backups'/('quality-preview-install-'+install_operation)
    state=json.loads(read(archive/'state.json'));before=json.loads(read(archive/'before.json'))
    backup=json.loads(read(archive/'backup-receipt.json'));receipt=state['receipt']
    require(state['stage']=='installed_disabled' and state['operation']==install_operation and state['image']==image
        and state['maintenance_operation']==operation and before['Image']==OLD_CONTROLLER_IMAGE
        and receipt['previous_image']==OLD_CONTROLLER_IMAGE and backup['backup_id']==install_operation
        and backup['backup_integrity']=='ok' and backup['restore_integrity']=='ok'
        and receipt['namespace']==namespace and receipt['image']==image and receipt['maintenance_sealed'] is True
        and receipt['data_mounts_preserved'] is True and backup['operation_id']==operation and backup['source_reset'] is False)
    installation=dict(install_operation=install_operation,previous_image=before['Image'],current_image=image,
        previous_container=before['Id'],current_container=receipt['container_id'])
    if not observe:
        require(about['maintenance'] is True)
        held,_=require_idle(namespace);require(held['operation_id']==operation)
        require(authority.identity==installation['current_container'])
    payload=dict(source_task=source,failed_task=failed,guard_sha256=guard,maintenance_operation=operation,installation=installation)
    try:
        result=subprocess.run(['docker','exec','-i','-w','/',authority.identity,'python','-c',PROGRAM,
            'observe' if observe else 'register'],input=json.dumps(payload),capture_output=True,text=True,timeout=120)
    except subprocess.TimeoutExpired:
        return dict(stage='observation_timeout',next_action='observe same recovery; never create a task manually',delivery_approval=False)
    require(result.returncode==0 and len(result.stdout.encode())<=16384 and authority.inspect_controller()==authority.identity)
    value=json.loads(result.stdout);require(value['delivery_approval'] is False)
    if value['receipt'] is not None:
        receipt=value['receipt'];require(receipt['source_task']==source and receipt['failed_task']==failed
            and receipt['tests_approved'] is False and receipt['model_calls']==0 and receipt['delivery_approval'] is False)
    else:require(observe)
    return value


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('namespace','image','source','failed-task','guard-sha','operation','install-operation'):p.add_argument('--'+key,required=True)
    p.add_argument('--observe',action='store_true');a=p.parse_args()
    print(json.dumps(run(a.namespace,a.image,a.source,a.failed_task,a.guard_sha,a.operation,a.install_operation,observe=a.observe),sort_keys=True))
