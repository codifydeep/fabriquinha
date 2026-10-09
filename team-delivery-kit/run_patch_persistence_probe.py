"""Credential-free fixed Docker launcher; synthetic evidence is never delivery approval."""
import argparse
import json
from pathlib import Path
import re
import subprocess
from docker_grouping import args as group_args


def command(image):
    if not re.fullmatch(r'sha256:[a-f0-9]{64}',image):raise ValueError('pinned local image ID required')
    probe=Path(__file__).resolve().with_name('probe_patch_persistence.py')
    return ['docker','run','--rm','--network','none','--read-only','--user','10000:10000',
        '--tmpfs','/tmp:rw,size=128m,mode=1777',*group_args('patch-persistence-probe','delivery-kit-port2'),
        '-e','PYTHONDONTWRITEBYTECODE=1','-e','HERMES_HOME=/tmp/hermes',
        '-e','HERMES_WRITE_SAFE_ROOT=/tmp','-e','TERMINAL_ENV=local','-e','TERMINAL_CWD=/tmp',
        '-v',str(probe)+':/probe_patch_persistence.py:ro','--entrypoint','python',image,
        '/probe_patch_persistence.py']


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image',required=True);options=parser.parse_args()
    result=subprocess.run(command(options.image),capture_output=True,text=True)
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
