"""Enroll one native feedback strategy under an exact sealed controller.

Metadata and a new persistent workflow only. Never wakes a model directly,
rewrites the exhausted source, resets counters or approves an artifact.
"""
import argparse
import json
from pathlib import Path
import subprocess
import os
from controller_maintenance_cli import arguments

PROGRAM='''import sys,json
sys.path.insert(0,"/")
import broker as b,literal_feedback_strategy as strategy
b.TOKEN=(b.STATE/"token").read_text()
qualification=json.loads(sys.stdin.read(65537))
result=strategy.enroll(b,sys.argv[1],qualification,sys.argv[2])
print(json.dumps(result,sort_keys=True))
'''


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('namespace','operation','source','qualification'):p.add_argument('--'+key,required=True)
    a=p.parse_args();target=arguments(a.namespace,'seal',a.operation)[4]
    import uuid
    if str(uuid.UUID(a.source))!=a.source:raise ValueError('canonical source identity required')
    path=Path(a.qualification)
    if path.is_symlink() or not path.is_file() or path.stat().st_size>65536:raise ValueError('bounded qualification file required')
    q=json.loads(path.read_text());labels=json.loads(subprocess.check_output(['docker','inspect','--format','{{json .Config.Labels}}',target],text=True))
    if labels.get('com.docker.compose.project')!=a.namespace or labels.get('com.docker.compose.service')!='execution-broker':
        raise ValueError('exact owned controller required')
    # Bind the caller's operation as well as the sealed stage checked by enroll.
    check='import sys,json;sys.path.insert(0,"/");import broker as b,controller_maintenance as m\nwith b.db() as c: print(json.dumps(m.current(c)))'
    state=json.loads(subprocess.check_output(['docker','exec',target,'python','-c',check],text=True,timeout=15))
    if not state or state.get('operation_id')!=a.operation or state.get('stage')!='sealed':raise ValueError('exact sealed operation required')
    try:
        r=subprocess.run(['docker','exec','-i','-w','/',target,'python','-c',PROGRAM,a.source,a.operation],
            input=json.dumps(q),text=True,capture_output=True,timeout=120)
    except subprocess.TimeoutExpired:
        print(json.dumps(dict(stage='observation_timeout',source_task=a.source,
            next_action='Observe existing enrollment journal and exact issue intent; never recreate metadata blindly',delivery_approval=False)));return
    if r.returncode:
        root=Path(__file__).resolve().parent/'.local-port2'/'probes';root.mkdir(mode=0o700,parents=True,exist_ok=True)
        diagnostic=root/('feedback-enrollment-'+a.operation+'-'+a.source+'.stderr.log')
        with os.fdopen(os.open(diagnostic,os.O_CREAT|os.O_APPEND|os.O_WRONLY|os.O_NOFOLLOW,0o600),'w') as out:out.write(r.stderr[:32768])
        raise RuntimeError('native feedback enrollment failed; private diagnostic: '+str(diagnostic))
    print(json.dumps(json.loads(r.stdout),sort_keys=True))


if __name__=='__main__':main()
