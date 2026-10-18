"""Operator-only qualification of one pre-model literal-author context repair."""
import argparse
import json
import subprocess
import uuid
from enroll_literal_maintenance import target

PROGRAM='''import sys,json;sys.path.insert(0,"/")
import broker as b,literal_author_bootstrap_recovery as recovery
r=recovery.register(b,sys.argv[1],sys.argv[2])
print(json.dumps({k:r[k] for k in ("operation","failed_task","attempt_limit","maintenance_author_retry_authorized","source_author_retry_authorized","source_reset","historical_http_absence_proven","pre_transport_guard_rejection_proven","execution_authorized","delivery_approval")},sort_keys=True))
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--namespace',required=True);parser.add_argument('--source-task',required=True)
    parser.add_argument('--failed-task',required=True);options=parser.parse_args()
    name=target(options.namespace,options.source_task)
    if str(uuid.UUID(options.failed_task))!=options.failed_task:raise ValueError('canonical failed task required')
    labels=json.loads(subprocess.check_output(['docker','inspect','--format','{{json .Config.Labels}}',name],text=True))
    if labels.get('com.docker.compose.project')!=options.namespace or labels.get('com.docker.compose.service')!='execution-broker':
        raise ValueError('exact owned controller required')
    value=subprocess.check_output(['docker','exec','-w','/',name,'python','-c',PROGRAM,options.source_task,options.failed_task],text=True,timeout=120)
    print(json.dumps(json.loads(value),sort_keys=True))


if __name__=='__main__':main()
