"""Operator-only admission of a fresh read-only CTO diagnosis; no worker API."""
import argparse
import json
import re
import subprocess
import uuid

READ_RECEIPT='''import sys;sys.path.insert(0,"/")
import model_proxy as p,json
from deterministic_read_dispatch import ledger
with ledger(p.COUNTER_PATH) as con:
 rows=con.execute("SELECT receipt FROM typed_decision_rejections WHERE execution_id=? AND upstream_sha256=?",sys.argv[1:]).fetchall()
 if len(rows)!=1:raise ValueError("exact persisted rejection required")
 print(rows[0][0])
'''
ADMIT='''import sys;sys.path.insert(0,"/")
import broker as b,json,test_diagnosis_recovery as recovery
print(json.dumps(recovery.resume(b,json.loads(sys.stdin.read())),sort_keys=True))
'''


def names(namespace):
    if not re.fullmatch(r'delivery-kit-[a-z0-9-]{1,48}',namespace):
        raise ValueError('owned exact namespace required')
    return namespace+'-model-proxy-1',namespace+'-execution-broker-1'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for arg in ('namespace','issue-id','failed-task','execution-id','upstream-sha256','operation-id'):
        parser.add_argument('--'+arg,required=True)
    args=parser.parse_args();proxy,broker=names(args.namespace)
    for field in ('issue_id','failed_task','execution_id','operation_id'):
        if str(uuid.UUID(getattr(args,field)))!=getattr(args,field):raise ValueError('canonical UUID required')
    if not re.fullmatch(r'[a-f0-9]{64}',args.upstream_sha256):raise ValueError('exact upstream digest required')
    for container,service in ((proxy,'model-proxy'),(broker,'execution-broker')):
        labels=json.loads(subprocess.check_output(['docker','inspect','--format','{{json .Config.Labels}}',container],text=True))
        if labels.get('com.docker.compose.project')!=args.namespace or labels.get('com.docker.compose.service')!=service:
            raise ValueError('owned exact service required')
    image=subprocess.check_output(['docker','inspect','--format','{{.Image}}',proxy],text=True).strip()
    receipt=json.loads(subprocess.check_output(['docker','exec','-w','/',proxy,'python','-c',READ_RECEIPT,
        args.execution_id,args.upstream_sha256],text=True))
    payload={key:getattr(args,key) for key in ('issue_id','failed_task','execution_id','operation_id')}
    payload.update(receipt=receipt,proxy_image=image)
    output=subprocess.check_output(['docker','exec','-i','-w','/',broker,'python','-c',ADMIT],
        input=json.dumps(payload),text=True)
    print(json.dumps(json.loads(output),sort_keys=True))


if __name__=='__main__':main()
