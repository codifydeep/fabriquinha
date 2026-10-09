"""Model-free, offline calibration of the newest-match browser detector."""
import argparse
from pathlib import Path
import re
import subprocess
from docker_grouping import args as grouped_args

ROOT=Path(__file__).resolve().parent


def command(image):
    if not re.fullmatch('sha256:[a-f0-9]{64}',image):raise ValueError('pinned browser image required')
    mounts=[(ROOT/'browser_feedback_latest.py','/browser_feedback_latest.py'),
            (ROOT/'tests/latest_browser_reference.py','/qualification.py')]
    if any(path.is_symlink() or not path.is_file() for path,_ in mounts):raise ValueError('trusted controls required')
    return ['docker','run','--rm',*grouped_args('latest-recipe-qualification',namespace='delivery-kit-port2'),
        '--network','none','--add-host','fixture:127.0.0.1','--read-only','--user','10000:10000',
        '--tmpfs','/tmp:rw,nosuid,nodev,size=256m','--env','HOME=/tmp',
        '--cap-drop','ALL','--security-opt','no-new-privileges','--memory','768m','--cpus','1',
        '--pids-limit','256','--shm-size','128m',
        *[part for path,target in mounts for part in ('--mount','type=bind,source='+str(path)+',target='+target+',readonly')],
        '--entrypoint','python',image,'/qualification.py']


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--image',required=True);args=parser.parse_args()
    subprocess.run(command(args.image),check=True,timeout=180)


if __name__=='__main__':main()
