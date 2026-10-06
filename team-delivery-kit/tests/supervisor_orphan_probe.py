"""Real SIGKILL/process/lock probe with a deterministic, model-free workload.

Uses the production supervisor/controller entrypoints and locks. Only external
delivery work and infrastructure probes are replaced, so this is NOT GitHub,
worker, launchd or application-delivery acceptance.
"""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
LABEL = 'ORPHAN-1'
ISSUE = '01a1111b-d664-78c6-9460-f9711fd39caf'
SLEEP = time.sleep


def write(path, value):
    path.write_text(json.dumps(value,sort_keys=True));path.chmod(0o600)


def workload(folder):
    entered = folder/'entered.json'
    previous = json.loads(entered.read_text()) if entered.exists() else []
    previous.append(os.getpid());write(entered,previous)
    deadline=time.monotonic()+15
    while not (folder/'release').exists():
        if time.monotonic()>deadline:
            raise RuntimeError('bounded fixture release timeout')
        SLEEP(.02)
    write(folder/'autonomy-status'/(LABEL+'.json'),dict(
        label=LABEL,issue_id=ISSUE,stage='deployed_qa_passed',fixture_only=True))


def child(role, folder):
    import portable_delivery as controller
    import portable_supervisor as supervisor
    controller.PRIVATE=folder;controller.LABEL=LABEL
    supervisor.PRIVATE=folder
    if role=='controller':
        with patch.object(controller,'from_environment',return_value={'fixture':True}), \
                patch.object(controller,'configure_run'), \
                patch.object(controller,'run_controller',side_effect=lambda _:workload(folder)):
            controller.main()
        return 0
    def run():
        return subprocess.run([sys.executable,str(Path(__file__).resolve()),
            '--role','controller','--folder',str(folder)],check=False).returncode
    with patch.object(supervisor,'verify_instance',return_value=[]), \
            patch.object(supervisor,'from_environment',return_value={'fixture':True}), \
            patch.object(supervisor,'load_run_spec',return_value={'label':LABEL}), \
            patch.object(supervisor,'run_delivery',side_effect=run), \
            patch.object(supervisor,'check_model_budget'), \
            patch.object(supervisor.time,'sleep',side_effect=lambda seconds:SLEEP(min(seconds,.05))), \
            patch.object(supervisor.sys,'argv',['portable_supervisor.py']), \
            patch('portable_test_revision_recovery.reconcile_ancestors',return_value=[]):
        return supervisor.main()


def until(predicate, seconds=10):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        value=predicate()
        if value:return value
        SLEEP(.02)
    raise RuntimeError('bounded process probe observation timeout')


def read(path):
    try:return json.loads(path.read_text())
    except (FileNotFoundError,json.JSONDecodeError):return None


def probe():
    first=second=None;orphan=None
    with tempfile.TemporaryDirectory(prefix='delivery-kit-orphan-probe-') as tmp:
        folder=Path(tmp).resolve();folder.chmod(0o700)
        (folder/'autonomy-status').mkdir()
        write(folder/'autonomy-status'/(LABEL+'.json'),dict(label=LABEL,issue_id=ISSUE,stage='accepted'))
        command=[sys.executable,str(Path(__file__).resolve()),'--role','supervisor','--folder',str(folder)]
        with (folder/'process.log').open('w+') as log:
            try:
                first=subprocess.Popen(command,stdout=log,stderr=log)
                orphan=until(lambda:read(folder/'entered.json'))[0]
                # Direct handle identifies the exact owned supervisor; never a
                # PID scan or broad kill. The unrelated host stack is untouched.
                first.kill();code=first.wait(timeout=5)
                if code!=-signal.SIGKILL:raise ValueError('real SIGKILL required')
                os.kill(orphan,0)
                second=subprocess.Popen(command,stdout=log,stderr=log)
                busy=until(lambda:(value if (value:=read(folder/'portable-supervisor'/(LABEL+'.json')))
                                   and value.get('stage')=='controller_busy' else None))
                if busy.get('unexpected_exits')!=0:
                    raise ValueError('orphan busy must not consume crash budget')
                if read(folder/'entered.json')!=[orphan]:
                    raise ValueError('duplicate active workload')
                (folder/'release').touch()
                if second.wait(timeout=10)!=0:raise ValueError('replacement supervisor failed')
                complete=read(folder/'autonomy-status'/(LABEL+'.json'))
                if complete.get('stage')!='deployed_qa_passed' or read(folder/'entered.json')!=[orphan]:
                    raise ValueError('same original workload must finish')
                log.flush();log.seek(0);output=log.read()
                if 'controller_busy' not in output:raise ValueError('actual controller lock denial required')
                return dict(status='passed',mode='real_processes_stub_workload',
                    initial_supervisor_pid=first.pid,initial_exit_code=code,
                    original_controller_pid=orphan,replacement_supervisor_pid=second.pid,
                    workload_executions=1,busy_observed=True,unexpected_exits=0,
                    original_child_completed=True,model_calls=0,
                    application_delivery_proven=False,launchd_recovery_proven=False)
            finally:
                # Release the original orphan normally, including failed-probe
                # cleanup. Direct Popen handles fence exact owned supervisors.
                (folder/'release').touch()
                for process in (first,second):
                    if process and process.poll() is None:
                        process.terminate()
                        try:process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            process.kill();process.wait(timeout=5)
                if orphan:
                    until(lambda:folder.joinpath('autonomy-status',LABEL+'.json').exists()
                        and (read(folder/'autonomy-status'/(LABEL+'.json')) or {}).get('stage')=='deployed_qa_passed',seconds=5)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--role',choices=('controller','supervisor'))
    parser.add_argument('--folder')
    parser.add_argument('--receipt')
    args=parser.parse_args()
    if args.role:
        folder=Path(args.folder).resolve()
        if not folder.is_dir() or not folder.name.startswith('delivery-kit-orphan-probe-'):
            raise ValueError('isolated probe folder required')
        return child(args.role,folder)
    result=probe()
    if args.receipt:
        path=Path(args.receipt)
        if not path.is_absolute() or path.is_symlink() or path.exists():
            raise ValueError('new absolute receipt required')
        write(path,result)
    print(json.dumps(result,sort_keys=True),flush=True)
    return 0


if __name__=='__main__':
    raise SystemExit(main())
