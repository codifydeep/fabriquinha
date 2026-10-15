"""Operator-only exact local-rejection repair; no agent-supplied evidence."""
import argparse
import json
import subprocess
from controller_maintenance_cli import arguments

PROGRAM='''import sys,json;sys.path.insert(0,"/")
import broker as b,generic_calibration_local_recovery as r
from generic_harness_calibration import digest
issue,author,operation=sys.argv[1:]
v=r.migrate(b,issue,author,operation)
print(json.dumps(dict(receipt_sha256=digest(v),author_task=author,failed_task=v["failed_task"],attempt_limit=v["attempt_limit"],author_restarted=v["author_restarted"],delivery_approval=v["delivery_approval"])))
'''


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--namespace',required=True)
    parser.add_argument('--issue',required=True);parser.add_argument('--author-task',required=True);parser.add_argument('--operation',required=True)
    options=parser.parse_args();owned=arguments(options.namespace,'seal',options.operation)[4]
    labels=json.loads(subprocess.check_output(['docker','inspect','--format','{{json .Config.Labels}}',owned],text=True))
    if labels.get('com.docker.compose.project')!=options.namespace or labels.get('com.docker.compose.service')!='execution-broker':
        raise ValueError('exact owned controller required')
    print(subprocess.check_output(['docker','exec','-w','/',owned,'python','-c',PROGRAM,
        options.issue,options.author_task,options.operation],text=True,timeout=45).strip())


if __name__=='__main__':main()
