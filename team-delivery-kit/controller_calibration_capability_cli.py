"""Operator-only bounded capability recovery; never print private receipts."""
import argparse
import json
import subprocess
from controller_maintenance_cli import arguments

PROGRAM='''import sys,json;sys.path.insert(0,"/")
import broker as b,generic_calibration_capability_recovery as recovery
from generic_harness_calibration import digest
issue,author,operation=sys.argv[1:]
try:
 r=recovery.migrate(b,issue,author,operation)
except TimeoutError:
 print(json.dumps({"stage":"probe_pending","author_task":author,"next_action":"observe_same_recorded_handle","author_restarted":False,"delivery_approval":False}))
else:
 print(json.dumps({"receipt_sha256":digest(r),"author_task":author,"failed_task":r["failed_task"],"attempt_limit":r["attempt_limit"],"author_restarted":r["author_restarted"],"delivery_approval":r["delivery_approval"]}))
'''


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--namespace',required=True)
    parser.add_argument('--issue',required=True);parser.add_argument('--author-task',required=True);parser.add_argument('--operation',required=True)
    options=parser.parse_args();owned=arguments(options.namespace,'seal',options.operation)[4]
    labels=json.loads(subprocess.check_output(['docker','inspect','--format','{{json .Config.Labels}}',owned],text=True))
    if labels.get('com.docker.compose.project')!=options.namespace or labels.get('com.docker.compose.service')!='execution-broker':
        raise ValueError('exact owned Compose controller required')
    value=subprocess.check_output(['docker','exec','-w','/',owned,'python','-c',PROGRAM,
        options.issue,options.author_task,options.operation],text=True,timeout=45)
    print(json.dumps(json.loads(value),sort_keys=True))


if __name__=='__main__':main()
