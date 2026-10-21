"""Operator-only recovery of the exact never-started empty-mount probe."""
import argparse
import json
import subprocess

from controller_maintenance_cli import arguments

PROGRAM='''import sys,json;sys.path.insert(0,"/")
import broker as b,calibration_capability_mount_recovery as recovery
from generic_harness_calibration import digest
b.TOKEN=(b.STATE/'token').read_text()
r=recovery.recover(b,*sys.argv[1:])
print(json.dumps(dict(operation=r['operation'],receipt_sha256=digest(r),
 job_key=r['job_key'],container_id=r['container_id'],
 observation_window_requalified=r['observation_window_requalified'],
 create_replayed=r['create_replayed'],start_replayed=r['start_replayed'],
 author_retry_authorized=r['author_retry_authorized'],delivery_approval=r['delivery_approval'])))
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--namespace',required=True)
    parser.add_argument('--issue',required=True)
    parser.add_argument('--author',required=True)
    parser.add_argument('--operation',required=True)
    args=parser.parse_args();owned=arguments(args.namespace,'seal',args.operation)[4]
    labels=json.loads(subprocess.check_output(['docker','inspect','--format','{{json .Config.Labels}}',owned],text=True))
    if labels.get('com.docker.compose.project')!=args.namespace or labels.get('com.docker.compose.service')!='execution-broker':
        raise ValueError('exact owned controller required')
    print(subprocess.check_output(['docker','exec','-w','/',owned,'python','-c',PROGRAM,
        args.issue,args.author,args.operation],text=True,timeout=45).strip())


if __name__=='__main__':main()
