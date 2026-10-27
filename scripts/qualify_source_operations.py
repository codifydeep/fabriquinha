"""Fresh local Git clone -> frozen source -> real paused Hermes operations.

No model route/key, Docker jobs, GitHub operations or product delivery. This
qualifies the public entry and single controller owner, not all of S6.
"""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import re

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from fabriquinha.effects import write_json
from fabriquinha.source import freeze, verify


def qualify(root,repository,revision,upstream,*,launchd=False):
    root=Path(root).resolve();repository=Path(repository).resolve();upstream=Path(upstream).resolve()
    if root.exists():raise ValueError('fresh private qualification root required')
    if root.is_relative_to(ROOT) and subprocess.run(['git','-C',str(ROOT),'check-ignore','--quiet',str(root)],capture_output=True).returncode:
        raise ValueError('qualification inside source checkout must use a Git-ignored private root')
    root.mkdir(mode=0o700,parents=True)
    subprocess.run(['git','clone','--no-local','--no-checkout','--',str(repository),str(root/'clone')],
        check=True,capture_output=True,timeout=60)
    source=root/'source';export=freeze(root/'clone',source,revision)
    write_json(root/'source-receipt.json',export)
    project=dict(version=1,namespace='delivery-kit-source-operations',repository='https://github.com/example/product',
        branch='release/source-fixture',validation_image='sha256:'+'a'*64,tests_dir='tests',
        reviewers={'backend':'lead','lead':'cto'},qualification=True)
    installation=root/'installation';installation.mkdir(mode=0o700)
    write_json(installation/'project.json',project)
    entry=source/'scripts/run_hermes_runtime.py'
    args=[sys.executable,'-B',str(entry),'--source',str(source),'--expect-source',export['source_digest'],
        '--python',sys.executable,'--root',str(installation),'--upstream',str(upstream)]
    # Do not let an operator's optional key/default route leak into a fixture.
    env={key:os.environ[key] for key in ('PATH','HOME','TMPDIR','LANG') if key in os.environ}
    env.update(PYTHONPATH=str(source/'src'),PYTHONSAFEPATH='1',PYTHONNOUSERSITE='1',
        PYTHONDONTWRITEBYTECODE='1',FABRIQUINHA_SOURCE_DIGEST=export['source_digest'])
    initialize='''
import json,sys
from pathlib import Path
from fabriquinha.runtime import Runtime
r=Runtime(Path(sys.argv[1]),Path(sys.argv[2]))
r.control.pause()
status=r.status()
assert status['control']['paused'] and status['control']['drained'] and not status['cards']
print(json.dumps({'pause':status['control']['episode']}))
'''
    started=subprocess.run([sys.executable,'-B','-c',initialize,str(installation),str(upstream)],env=env,
        capture_output=True,text=True,timeout=45)
    write_json(root/'initialize.json',dict(code=started.returncode,stdout=started.stdout,stderr=started.stderr))
    if started.returncode:raise RuntimeError('fresh initialization failed; preserve private diagnostics')
    episode=json.loads(started.stdout)['pause'];services=[]

    def cli(operation,*extra,success=True):
        reply=subprocess.run([*args,operation,*extra],env=env,capture_output=True,text=True,timeout=30)
        write_json(root/('command-'+operation+'-'+str(time.time_ns())+'.json'),
            dict(code=reply.returncode,stdout=reply.stdout,stderr=reply.stderr))
        if success:
            if reply.returncode:raise RuntimeError('public operation failed: '+operation)
            return json.loads(reply.stdout)
        assert reply.returncode!=0

    def start():
        with (root/('service-'+str(len(services)+1)+'.log')).open('xb') as log:
            os.chmod(log.name,0o600)
            service=subprocess.Popen([*args,'serve','--interval','0.1'],env=env,stdin=subprocess.DEVNULL,
                stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        services.append(service)
        deadline=time.monotonic()+30
        while time.monotonic()<deadline:
            if service.poll() is not None:raise RuntimeError('managed service ended; preserve log')
            path=installation/'status.json'
            if path.exists():
                status=json.loads(path.read_bytes())
                if status['dispatcher_pid']==service.pid and status['dispatcher_state']=='running':
                    assert status['board']['control']['paused'] and status['board']['control']['episode']==episode
                    assert status['board']['control']['drained'] and not status['board']['cards']
                    return service
            time.sleep(0.1)
        raise TimeoutError('managed startup observation expired')

    def stop(service):
        if service.poll() is None:service.send_signal(signal.SIGTERM)
        service.wait(timeout=15);assert service.returncode==0

    launch_service=None
    def launchctl(*arguments,success=True):
        result=subprocess.run(['launchctl',*arguments],capture_output=True,text=True,timeout=15)
        if success and result.returncode:raise RuntimeError('launchd operation failed: '+result.stderr[:1000])
        return result
    def observed_pid(previous=None):
        deadline=time.monotonic()+100
        while time.monotonic()<deadline:
            value=launchctl('print',launch_service)
            match=re.search(r'\n\s*pid = (\d+)',value.stdout)
            pid=int(match[1]) if match else None
            if pid and pid!=previous and re.search(r'\n\s*state = running\s*\n',value.stdout):
                # launchd's live job state is authoritative. kill(pid, 0) may
                # be denied across macOS process-security domains even for a
                # readable, correctly owned job; denial is not proof of death.
                state=json.loads((installation/'status.json').read_bytes())
                if (state.get('dispatcher_pid')==pid and state.get('dispatcher_state')=='running'
                        and 0<=time.time()-state.get('observed_at',0)<30):
                    assert state['board']['control']['paused'] and state['board']['control']['drained']
                    assert state['board']['control']['episode']==episode
                    return pid
            time.sleep(.25)
        raise TimeoutError('same launchd job observation expired; inspect, never duplicate bootstrap')
    try:
        first=start()
        cli('serve',success=False)  # Native Owner lock, no second dispatcher.
        assert first.poll() is None
        status=cli('status');assert status['control']['paused'] and status['control']['drained']
        cli('resume','--expect-pause','0'*32,success=False)
        assert cli('pause')['control']['episode']==episode
        stop(first)
        second=start()
        assert cli('status')['control']['episode']==episode
        stop(second)
        if launchd:
            if sys.platform!='darwin':raise ValueError('launchd qualification is macOS only')
            prepare_args=[sys.executable,'-B',str(source/'scripts/prepare_hermes_launchagent.py'),
                  '--source',str(source),'--expect-source',export['source_digest'],
                  '--python',sys.executable,'--root',str(installation),'--upstream',str(upstream)]
            prepared=json.loads(subprocess.check_output(prepare_args,text=True))
            domain='gui/'+str(os.getuid());target=domain+'/'+prepared['label']
            if launchctl('print',target,success=False).returncode==0:raise ValueError('existing launchd job; preserve it')
            launchctl('bootstrap',domain,prepared['plist']);launch_service=target
            pid=observed_pid()
            cli('serve',success=False)
            launchctl('kill','SIGABRT',target)  # Crash (not intentional SIGKILL); core dumps disabled in plist.
            replacement=observed_pid(pid);assert replacement!=pid
            launchctl('bootout',target);launch_service=None
            deadline=time.monotonic()+40
            while launchctl('print',target,success=False).returncode==0:
                if time.monotonic()>deadline:raise TimeoutError('bootout acknowledged; observe same job without repeating it')
                time.sleep(.25)
        # Drift in our own stopped fixture; never alter an installed delivery.
        changed=source/'src/fabriquinha/config.py';original=changed.read_bytes()
        changed.chmod(0o600);changed.write_bytes(original+b'\n# fixture drift\n');changed.chmod(0o400)
        cli('status',success=False)
        changed.chmod(0o600);changed.write_bytes(original);changed.chmod(0o400)
        verify(source,export['source_digest'])
        from sqlite3 import connect
        with connect(installation/'home/kanban.db') as conn:
            assert conn.execute('SELECT COUNT(*) FROM task_runs').fetchone()[0]==0
            assert conn.execute('SELECT COUNT(*) FROM tasks').fetchone()[0]==0
        assert not (installation/'route.json').exists() and not (installation/'provider-policy.json').exists()
        result=dict(source=export['commit'],source_digest=export['source_digest'],source_files=export['files'],
            fresh_git_clone=True,fresh_native_board=True,managed_paused_start=True,native_single_owner=True,
            pause_survives_restart=True,stale_resume_refused=True,source_drift_refused=True,
            services_stopped=True,native_runs=0,model_calls=0,github_mutations=0,docker_jobs=0,
            delivery_approval=False,complete_installer=False)
        if launchd:result.update(launchd_paused_start=True,launchd_crash_restarted=True,launchd_job_unloaded=True)
        write_json(root/'receipt.json',result);print(json.dumps(result,indent=2));return result
    finally:
        if launch_service:launchctl('bootout',launch_service)
        for service in services:
            if service.poll() is None:stop(service)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True);parser.add_argument('--repository',type=Path,required=True)
    parser.add_argument('--revision',required=True);parser.add_argument('--upstream',type=Path,required=True)
    parser.add_argument('--launchd',action='store_true')
    args=parser.parse_args();qualify(args.root,args.repository,args.revision,args.upstream,launchd=args.launchd)
