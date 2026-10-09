"""Fixed source-to-image inventory for scope integration qualification.

Only public runtime code hashes are inspected. No installation state, secrets,
agent dispatch or permission changes. A passing inventory is not E2E delivery.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
from docker_grouping import args as group_args

ROOT=Path(__file__).resolve().parent
BROKER=['server','native','native_scope_note','handoffs','handoff_runtime','adapted_test_review',
        'test_revision_review','validation_job','test_first_job','review_context_recovery',
        'execution_diagnosis_recovery','worker_recovery_transport',
        'product_scope_revision','product_scope_ledger','product_scope_execution',
        'product_scope_materialize','product_scope_job','product_scope_base_verify',
        'product_scope_registration','product_scope_task_binding','product_scope_worker',
        'product_scope_author','product_scope_delivery','product_scope_review','delivery_code_inspection','product_scope_bootstrap',
        'product_scope_pipeline','product_scope_envelope_recovery','product_scope_mount_recovery']
PROXY=['product_scope_contract','decision_schema','typed_decision_contract']
PROGRAM='''import sys,json,hashlib
from pathlib import Path
expected=json.loads(sys.argv[1]);missing=[];changed=[]
for name,sha in expected.items():
 path=Path(name)
 if not path.is_file() or path.is_symlink():missing.append(name)
 elif hashlib.sha256(path.read_bytes()).hexdigest()!=sha:changed.append(name)
print(json.dumps(dict(operation="scope_runtime_inventory_v1",checked=len(expected),missing=missing,changed=changed,delivery_approval=False)))
raise SystemExit(int(bool(missing or changed)))
'''


def manifest(role,root=ROOT):
    if role not in ('broker','proxy'):raise ValueError('fixed runtime role required')
    paths={('/broker.py' if name=='server' else '/'+name+'.py'):root/'broker'/(name+'.py') for name in BROKER} if role=='broker' else {}
    paths.update({'/'+name+'.py':root/(name+'.py') for name in (['product_scope_contract'] if role=='broker' else PROXY)})
    if any(p.is_symlink() or not p.is_file() for p in paths.values()):raise ValueError('complete public source inventory required')
    return {name:hashlib.sha256(path.read_bytes()).hexdigest() for name,path in paths.items()}


def command(image,role):
    if not re.fullmatch(r'sha256:[a-f0-9]{64}',image):raise ValueError('immutable local image ID required')
    expected=manifest(role)
    return ['docker','run','--rm','--name','delivery-kit-port2-scope-'+role+'-inventory',
            *group_args('scope-'+role+'-inventory',namespace='delivery-kit-port2'),
            '--network=none','--read-only','--cap-drop=ALL','--security-opt=no-new-privileges',
            '--memory=128m','--pids-limit=16','--entrypoint','python',image,'-c',PROGRAM,json.dumps(expected,sort_keys=True)]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image',required=True);parser.add_argument('--role',choices=('broker','proxy'),required=True)
    a=parser.parse_args()
    raise SystemExit(subprocess.run(command(a.image,a.role)).returncode)

if __name__=='__main__':main()
