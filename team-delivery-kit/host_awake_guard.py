"""Bounded macOS idle-sleep guard for one authorized local Docker trial.

No global power settings, display assertion, lid override, model calls or writes
to Docker. The optional system-sleep assertion only applies on AC power.
The assertion ends on idle, duration limit, error or process exit.
"""
import argparse
import json
import platform
import re
import subprocess
import time


def active_workers(project):
    result=subprocess.run(['docker','ps','--filter','label=com.docker.compose.project='+project,
        '--filter','label=delivery-kit.owner='+project+'-broker-v1','--format','{{.Names}}'],
        capture_output=True,text=True,timeout=5,check=True)
    return sum(name.startswith(project+'-job-') for name in result.stdout.splitlines())


def run(project,duration=1800,idle_grace=300,*,popen=subprocess.Popen,active=active_workers,
        clock=time.monotonic,sleep=time.sleep,report=lambda x:print(json.dumps(x),flush=True),
        prevent_system_sleep_on_ac=False):
    if (type(prevent_system_sleep_on_ac) is not bool
            or not re.fullmatch(r'delivery-kit-[a-z0-9-]{1,40}',project)
            or not 60<=duration<=3600 or not 10<=idle_grace<=duration):
        raise ValueError('bounded isolated project guard required')
    command=['/usr/bin/caffeinate','-i']
    if prevent_system_sleep_on_ac:command.append('-s')
    child=popen(command+['-t',str(duration)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    start=clock();last_active=start
    report(dict(project=project,stage='idle_sleep_guard_started',max_seconds=duration,
        assertion='system_sleep_on_ac_and_idle' if prevent_system_sleep_on_ac else 'idle_system_sleep_only'))
    try:
        while clock()-start<duration:
            if child.poll() is not None:raise RuntimeError('sleep assertion exited')
            if active(project):last_active=clock()
            elif clock()-last_active>=idle_grace:return 'idle'
            sleep(min(10,duration-(clock()-start)))
        return 'duration_limit'
    finally:
        if child.poll() is None:child.terminate()
        child.wait(timeout=5)
        report(dict(project=project,stage='idle_sleep_guard_stopped'))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--project',required=True)
    p.add_argument('--duration',type=int,default=1800);p.add_argument('--idle-grace',type=int,default=300)
    p.add_argument('--prevent-system-sleep-on-ac',action='store_true')
    args=p.parse_args()
    if platform.system()!='Darwin':raise SystemExit('This guard is macOS-only.')
    run(args.project,args.duration,args.idle_grace,
        prevent_system_sleep_on_ac=args.prevent_system_sleep_on_ac)
