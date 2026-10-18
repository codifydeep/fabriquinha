"""Qualify, or observe the same readonly job for, one canonical base recovery."""
import argparse
import json
import subprocess
from enroll_literal_maintenance import target

PROGRAM='''import sys,json;sys.path.insert(0,"/")
import broker as b,literal_base_recovery as recovery
try:
 receipt=recovery.register(b,sys.argv[1])
 print(json.dumps({k:receipt[k] for k in ("operation","attempt_limit","source_reset","author_retry_authorized","execution_authorized","delivery_approval")},sort_keys=True))
except TimeoutError:
 print(json.dumps({"stage":"observe_same_qualification","source_reset":False,"delivery_approval":False}))
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--namespace',required=True);parser.add_argument('--source-task',required=True);options=parser.parse_args()
    name=target(options.namespace,options.source_task)
    labels=json.loads(subprocess.check_output(['docker','inspect','--format','{{json .Config.Labels}}',name],text=True))
    if labels.get('com.docker.compose.project')!=options.namespace or labels.get('com.docker.compose.service')!='execution-broker':
        raise ValueError('exact owned controller required')
    result=subprocess.check_output(['docker','exec','-w','/',name,'python','-c',PROGRAM,options.source_task],text=True,timeout=120)
    print(json.dumps(json.loads(result),sort_keys=True))


if __name__=='__main__':main()
