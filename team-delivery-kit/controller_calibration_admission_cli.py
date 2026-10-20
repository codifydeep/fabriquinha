"""Operator-only late unused admission recovery; no worker endpoint or shell payload."""
import argparse
import json
import subprocess

from controller_maintenance_cli import arguments

PROGRAM='''import sys,json;sys.path.insert(0,"/")
import broker as b,calibration_admission_recovery as recovery
from generic_harness_calibration import digest
b.TOKEN=(b.STATE/'token').read_text()
value=recovery.recover(b,*sys.argv[1:])
print(json.dumps(dict(operation=value['operation'],receipt_sha256=digest(value),
 failed_task=value['failed_task']['id'],infrastructure_attempt_limit=value['infrastructure_attempt_limit'],
 retry_budget_reset=value['retry_budget_reset'],author_retry_authorized=value['author_retry_authorized'],
 delivery_approval=value['delivery_approval'])))
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--namespace',required=True)
    parser.add_argument('--recovery',required=True)
    parser.add_argument('--operation',required=True)
    args=parser.parse_args();owned=arguments(args.namespace,'seal',args.operation)[4]
    labels=json.loads(subprocess.check_output(['docker','inspect','--format','{{json .Config.Labels}}',owned],text=True))
    if labels.get('com.docker.compose.project')!=args.namespace or labels.get('com.docker.compose.service')!='execution-broker':
        raise ValueError('exact owned controller required')
    print(subprocess.check_output(['docker','exec','-w','/',owned,'python','-c',PROGRAM,
        args.recovery,args.operation],text=True,timeout=45).strip())


if __name__=='__main__':main()
