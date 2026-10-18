"""Operator-only enrollment of a source-bound frozen-harness counterexample.

Requires sealed maintenance, no active workers, and an authenticated technical
hold. Does not release the maintenance barrier, reset source attempts or approve
any delivery. The receipt is private installation data, never public Git input.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import uuid

PROGRAM='''import sys,json;sys.path.insert(0,"/")
import broker as b,literal_maintenance_effects as maintenance
with b.LOCK: result=maintenance.enroll(b,sys.argv[1],json.load(sys.stdin))
print(json.dumps(result,sort_keys=True))
'''


def target(namespace,source):
    if not re.fullmatch(r'delivery-kit-[a-z0-9-]{1,48}',namespace):raise ValueError('exact namespace required')
    if str(uuid.UUID(source))!=source:raise ValueError('canonical source task required')
    return namespace+'-execution-broker-1'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--namespace',required=True);parser.add_argument('--source-task',required=True)
    parser.add_argument('--receipt',required=True,type=Path);options=parser.parse_args()
    name=target(options.namespace,options.source_task)
    if options.receipt.is_symlink() or options.receipt.stat().st_size>131072:raise ValueError('bounded local receipt required')
    receipt=json.loads(options.receipt.read_text())
    labels=json.loads(subprocess.check_output(['docker','inspect','--format','{{json .Config.Labels}}',name],text=True))
    if labels.get('com.docker.compose.project')!=options.namespace or labels.get('com.docker.compose.service')!='execution-broker':
        raise ValueError('exact owned controller required')
    result=subprocess.check_output(['docker','exec','-i','-w','/',name,'python','-c',PROGRAM,options.source_task],
        input=json.dumps(receipt),text=True,timeout=120)
    print(json.dumps(json.loads(result),sort_keys=True))


if __name__=='__main__':main()
