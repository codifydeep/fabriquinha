"""Operator-only qualification of a preserved failed protocol for review."""
import argparse
import json
import subprocess
from enroll_literal_maintenance import target

PROGRAM='''import sys,json;sys.path.insert(0,"/")
import broker as b,literal_failed_inspection_review as review
r=review.register(b,sys.argv[1])
print(json.dumps({k:r[k] for k in ("operation","attempt_limit","author_retry_authorized","source_reset","execution_authorized","delivery_approval")},sort_keys=True))
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--namespace',required=True);parser.add_argument('--source-task',required=True);options=parser.parse_args()
    name=target(options.namespace,options.source_task)
    labels=json.loads(subprocess.check_output(['docker','inspect','--format','{{json .Config.Labels}}',name],text=True))
    if labels.get('com.docker.compose.project')!=options.namespace or labels.get('com.docker.compose.service')!='execution-broker':
        raise ValueError('exact owned controller required')
    value=subprocess.check_output(['docker','exec','-w','/',name,'python','-c',PROGRAM,options.source_task],text=True,timeout=120)
    print(json.dumps(json.loads(value),sort_keys=True))


if __name__=='__main__':main()
