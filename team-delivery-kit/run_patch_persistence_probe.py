"""Credential-free fixed Docker launcher; synthetic evidence is never delivery approval."""
import argparse
import json
from pathlib import Path
import re
import subprocess
from docker_grouping import args as group_args


def command(image,observed=False):
    if not re.fullmatch(r'sha256:[a-f0-9]{64}',image):raise ValueError('pinned local image ID required')
    probe=Path(__file__).resolve().with_name('probe_patch_persistence.py')
    root='/workspace' if observed else '/tmp'
    return ['docker','run','--rm','--network','none','--read-only','--user','0:0' if observed else '10000:10000',
        '--tmpfs','/tmp:rw,size=128m,mode=1777',*group_args('patch-persistence-probe','delivery-kit-port2'),
        '-e','PYTHONDONTWRITEBYTECODE=1','-e','HERMES_HOME=/tmp/hermes',
        '-e','HERMES_WRITE_SAFE_ROOT='+root,'-e','TERMINAL_ENV=local','-e','TERMINAL_CWD='+root,
        *(['--cap-drop','ALL','--cap-add','SETUID','--cap-add','SETGID',
           '--tmpfs','/workspace:rw,size=1m,mode=1777','-e','DELIVERY_EXECUTION_MODE=implementation',
           '-e','HERMES_FENCED_INPLACE_WRITES=1','-e','DELIVERY_PROBE_REQUIRE_OBSERVATION=1'] if observed else []),
        '-v',str(probe)+':/probe_patch_persistence.py:ro','--entrypoint','python',image,
        '/probe_patch_persistence.py']


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image',required=True);parser.add_argument('--observed',action='store_true');options=parser.parse_args()
    result=subprocess.run(command(options.image,options.observed),capture_output=True,text=True)
    if result.returncode:
        raise ValueError('synthetic installed-handler qualification failed; no authorization issued')
    receipt=json.loads(result.stdout)
    if (receipt.get('operation')!='installed_patch_persistence_probe_v1'
            or receipt.get('synthetic_only') is not True or receipt.get('historical_cause')!='unknown'
            or any(receipt.get(k) is not False for k in
                   ('product_files_modified','delivery_approval','author_retry_authorized'))):
        raise ValueError('invalid nonauthorizing synthetic receipt')
    print(json.dumps(dict(image=options.image,receipt=receipt),sort_keys=True))


if __name__=='__main__':main()
