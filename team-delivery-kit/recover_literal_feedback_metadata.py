"""Recover only the proven pre-author typed-metadata mismatch, under maintenance."""
import argparse
import json
import subprocess
import uuid
from controller_maintenance_cli import arguments

PROGRAM='''import sys,json;sys.path.insert(0,"/")
import broker as b,literal_feedback_strategy as strategy
b.TOKEN=(b.STATE/"token").read_text()
r=strategy.recover_metadata_bound(b,sys.argv[1],sys.argv[2])
print(json.dumps({k:r[k] for k in ("operation","workflow_key","config_sha256","typed_reason_limit","legacy_local_reason_limit","reason_characters","source_reset","author_retry_authorized","native_author_started","delivery_approval")},sort_keys=True))
'''


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('namespace','operation','workflow'):p.add_argument('--'+k,required=True)
    a=p.parse_args();target=arguments(a.namespace,'seal',a.operation)[4]
    if str(uuid.UUID(a.workflow))!=a.workflow:raise ValueError('canonical workflow required')
    labels=json.loads(subprocess.check_output(['docker','inspect','--format','{{json .Config.Labels}}',target],text=True))
    if labels.get('com.docker.compose.project')!=a.namespace or labels.get('com.docker.compose.service')!='execution-broker':raise ValueError('owned controller required')
    print(subprocess.check_output(['docker','exec','-w','/',target,'python','-c',PROGRAM,a.workflow,a.operation],text=True,timeout=60).strip())


if __name__=='__main__':main()
