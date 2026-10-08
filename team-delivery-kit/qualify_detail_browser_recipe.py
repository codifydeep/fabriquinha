"""Model-free qualification of the fixed recipe against a synthetic reference.

The fixture never leaves this one-off container; it is not product implementation
and cannot supply product tests, a PR, a review, or homologation evidence.
"""
import argparse
from pathlib import Path
import re
import subprocess
from docker_grouping import args as grouped_args

ROOT=Path(__file__).resolve().parent


def command(image):
    if not re.fullmatch('sha256:[a-f0-9]{64}',image):raise ValueError('pinned browser image required')
    mounts=[(ROOT/'browser_feedback_detail.py','/browser_feedback_detail.py'),
            (ROOT/'tests/detail_browser_reference.py','/qualification.py')]
    if any(p.is_symlink() or not p.is_file() for p,_ in mounts):raise ValueError('trusted recipes required')
    return ['docker','run','--rm',*grouped_args('detail-recipe-qualification',namespace='delivery-kit-port2'),
        '--network','none','--add-host','fixture:127.0.0.1','--read-only','--user','10000:10000',
        '--tmpfs','/tmp:rw,nosuid,nodev,size=256m','--env','HOME=/tmp',
        '--cap-drop','ALL','--security-opt','no-new-privileges','--memory','768m','--cpus','1',
        '--pids-limit','256','--shm-size','128m',
        *[part for p,target in mounts for part in ('--mount','type=bind,source='+str(p)+',target='+target+',readonly')],
        '--entrypoint','python',image,'/qualification.py']


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--image',required=True);a=parser.parse_args()
    subprocess.run(command(a.image),check=True,timeout=180)


if __name__=='__main__':main()
