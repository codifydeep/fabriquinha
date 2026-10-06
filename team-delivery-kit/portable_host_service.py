"""One pinned host-service tick. launchd schedules ticks and restarts crashes.

No agent/issue creation, credential storage, gate override or arbitrary command
configuration. Completed releases are idle; technical blockers remain visible.
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid

from publication_access import require_access, WaitingPublicationAccess

ROOT = Path(__file__).resolve().parent
ENV_KEYS = {'DELIVERY_KIT_INSTANCE_HOME', 'DELIVERY_KIT_PROJECT_CONFIG',
    'DELIVERY_KIT_COMPOSE_PROJECT', 'EVAL_BACKEND_PORT', 'EVAL_FRONTEND_PORT',
    'DELIVERY_KIT_DELIVERY_CONTRACT', 'DELIVERY_KIT_RUN_SPEC', 'DELIVERY_KIT_TEST_FIRST'}
COMPLETE = {'deployed_qa_passed', 'qa_recovered_by_child', 'recovered_by_test_revision'}


def read_object(path, limit=65536):
    path = Path(path)
    if (not path.is_absolute() or any(p.is_symlink() for p in (path, *path.parents))
            or not path.is_file() or path.stat().st_size > limit):
        raise ValueError('unsafe service input')
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError('service object required')
    return value


def load_config(path, pin):
    config = read_object(path)
    actual = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    if not re.fullmatch(r'[a-f0-9]{64}', pin) or actual != pin:
        raise ValueError('host service registration drift')
    if set(config) != {'schema', 'label', 'issue_id', 'environment', 'inputs'} or config['schema'] != 1:
        raise ValueError('invalid host service fields')
    if str(uuid.UUID(config['issue_id'])) != config['issue_id']:
        raise ValueError('invalid service issue')
    env = config['environment']
    if (not isinstance(env, dict) or set(env) != ENV_KEYS
            or any(not isinstance(v, str) or '\x00' in v or '\n' in v for v in env.values())
            or env['DELIVERY_KIT_TEST_FIRST'] not in ('0', '1')
            or not re.fullmatch(r'delivery-kit-[a-z0-9-]{1,48}', env['DELIVERY_KIT_COMPOSE_PROJECT'])
            or any(not env[k].isdigit() or not 1024 <= int(env[k]) <= 65535
                   for k in ('EVAL_BACKEND_PORT', 'EVAL_FRONTEND_PORT'))):
        raise ValueError('invalid service environment')
    required = {env[k] for k in ('DELIVERY_KIT_PROJECT_CONFIG',
        'DELIVERY_KIT_DELIVERY_CONTRACT', 'DELIVERY_KIT_RUN_SPEC')}
    if set(config['inputs']) != required:
        raise ValueError('service source pins required')
    for filename, digest in config['inputs'].items():
        read_object(filename)
        if hashlib.sha256(Path(filename).read_bytes()).hexdigest() != digest:
            raise ValueError('service source drift')
    project = read_object(env['DELIVERY_KIT_PROJECT_CONFIG'])
    contract = read_object(env['DELIVERY_KIT_DELIVERY_CONTRACT'])
    spec = read_object(env['DELIVERY_KIT_RUN_SPEC'])
    if (project.get('repository') != contract.get('repository')
            or spec.get('label') != config['label']
            or not re.fullmatch(r'[A-Z][A-Z0-9]{1,31}-[1-9][0-9]{0,5}', config['label'])):
        raise ValueError('service repository or label drift')
    private = Path(env['DELIVERY_KIT_INSTANCE_HOME'])
    if (not private.is_absolute() or any(p.is_symlink() for p in (private, *private.parents))
            or not private.is_dir() or private.stat().st_mode & 0o077):
        raise ValueError('private service home required')
    context = read_object(private / ('portable-context-' + config['label'] + '.json'))
    if context.get('issue_id') != config['issue_id']:
        raise ValueError('existing issue binding required')
    return config


def tick(config, previous, status, run, ready, access, can_refresh):
    """All side effects remain in the existing locked controller."""
    if status.get('issue_id') != config['issue_id'] or status.get('label') != config['label']:
        raise ValueError('host service status identity drift')
    if status.get('stage') in COMPLETE:
        return dict(stage='completed_idle', controller_started=False)
    if previous.get('stage') == 'crash_escalation':
        return previous
    if not ready():
        return dict(stage='waiting_infrastructure', controller_started=False)
    from portable_supervisor import STOP
    if status.get('stage') in STOP and not can_refresh(status):
        return dict(stage='technical_blocked', controller_started=False,
                    category=status.get('category', status['stage']))
    if status.get('stage') == 'waiting_publication_access':
        try:
            access()
        except WaitingPublicationAccess as error:
            return dict(stage='waiting_publication_access', category=str(error), controller_started=False)
    code = run()
    crashes = previous.get('unexpected_exits', 0)
    if type(crashes) is not int or crashes < 0:
        raise ValueError('invalid service crash history')
    if code not in (0, 75):
        crashes += 1
    elif code == 0:
        crashes = 0
    return dict(stage=('crash_escalation' if crashes >= 2 else 'controller_returned'),
                controller_started=True, child_exit_code=code, unexpected_exits=crashes)


def initial_status(config, private, writer):
    """Initialize observation only; never bypass an existing verdict or gate."""
    path = private / 'autonomy-status' / (config['label'] + '.json')
    if path.exists() or path.is_symlink():
        return read_object(path)
    context = read_object(private / ('portable-context-' + config['label'] + '.json'))
    if context.get('issue_id') != config['issue_id'] or context.get('label') != config['label']:
        raise ValueError('bootstrap observation identity drift')
    value = dict(label=config['label'], issue_id=config['issue_id'], stage='waiting_approval',
                 owner='durable_handoff_controller', updated_at=time.time())
    writer(path, value)
    return value


def sync_test_blocker(value,managed,private,writer):
    """Project a new real blocker without starting/retrying any execution."""
    if (value.get('stage')!='escalation_required' or not managed
            or managed.get('route',{}).get('issue_id')!=value.get('issue_id')):return False
    state=managed.get('state') or {};data=json.loads(state.get('data','{}'))
    error=data.get('error')
    if (state.get('stage')!='test_first_blocked' or not isinstance(error,str)
            or not re.fullmatch(r'[A-Za-z0-9_:. -]{1,180}',error)):return False
    category='test_first_blocked:'+error
    if value.get('category')==category:return False
    digest=hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()
    archive=private/'autonomy-status'/'history'/(value['label']+'-'+digest+'.json')
    if (private/'autonomy-status').is_symlink() or archive.parent.is_symlink():
        raise ValueError('unsafe projection directory')
    (private/'autonomy-status').mkdir(mode=0o700,exist_ok=True)
    if archive.is_symlink():raise ValueError('unsafe projection archive')
    if archive.exists():
        if read_object(archive)!=value:raise ValueError('projection archive drift')
    else:writer(archive,value)
    current=dict(value,category=category,owner='cto',source_task=state.get('source_task'),
                 updated_at=time.time())
    writer(private/'autonomy-status'/(value['label']+'.json'),current)
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    parser.add_argument('--pin', required=True)
    args = parser.parse_args()
    config = load_config(args.config, args.pin)
    # Remove inherited run/fault overrides before importing environment-bound
    # modules or spawning the child. Never store credentials in registration.
    for key in list(os.environ):
        if key.startswith(('DELIVERY_KIT_', 'EVAL_')):
            os.environ.pop(key)
    os.environ.update(config['environment'])
    from release_eval import save_receipt
    private = Path(config['environment']['DELIVERY_KIT_INSTANCE_HOME'])
    folder = private / 'host-service'
    folder.mkdir(mode=0o700, exist_ok=True)
    receipt_path = folder / (config['label'] + '.json')
    lock_path = folder / (config['label'] + '.lock')
    if any(path.is_symlink() for path in (folder, receipt_path, lock_path)):
        raise ValueError('unsafe service state')
    with lock_path.open('a+') as lock:
        os.chmod(lock_path, 0o600)
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0
        previous = read_object(receipt_path) if receipt_path.exists() else {}
        if previous and (previous.get('registration_pin') != args.pin
                or previous.get('issue_id') != config['issue_id']):
            raise ValueError('host service receipt binding drift')
        status = initial_status(config, private, save_receipt)
        def ready():
            try:
                result = subprocess.run(['docker', 'info', '--format', '{{.ServerVersion}}'],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
                if result.returncode:
                    return False
                from evalctl import verify
                return not verify()
            except (OSError, subprocess.TimeoutExpired):
                return False
        def refresh(value):
            from portable_supervisor import (stale_restart_blocker,
                stale_size_blocker, stale_review_transport_blocker, stale_execution_diagnosis_blocker,
                stale_worker_interruption_blocker, stale_artifact_diagnosis_blocker)
            from portable_delivery import configure_run, read_context, managed_handoff
            from portable_contract import from_environment
            contract = from_environment(); configure_run(contract)
            managed = managed_handoff(read_context(contract))
            sync_test_blocker(value,managed,private,save_receipt)
            from automatic_restart_diagnosis import reconcile
            if reconcile(private, config['environment']['DELIVERY_KIT_COMPOSE_PROJECT'], value, managed):
                managed = managed_handoff(read_context(contract))
            from automatic_worker_interruption import reconcile as reconcile_worker
            if reconcile_worker(private, config['environment']['DELIVERY_KIT_COMPOSE_PROJECT'], value, managed):
                managed = managed_handoff(read_context(contract))
            return any(check(value, managed) for check in (
                stale_restart_blocker, stale_size_blocker, stale_review_transport_blocker,
                stale_execution_diagnosis_blocker, stale_worker_interruption_blocker,
                stale_artifact_diagnosis_blocker))
        def run():
            return subprocess.run([sys.executable, '-u', str(ROOT / 'portable_supervisor.py'),
                '--managed-label', config['label']], cwd=ROOT, env=os.environ.copy()).returncode
        result = tick(config, previous, status, run, ready, require_access, refresh)
        value = {**result, 'label': config['label'], 'issue_id': config['issue_id'],
                 'registration_pin': args.pin, 'updated_at': time.time()}
        # Keep the full prior crash evidence while waiting for external access.
        if 'unexpected_exits' not in value and previous.get('unexpected_exits'):
            value['unexpected_exits'] = previous['unexpected_exits']
        save_receipt(receipt_path, value)
        if {k:v for k,v in previous.items() if k != 'updated_at'} != {k:v for k,v in value.items() if k != 'updated_at'}:
            print(json.dumps(value, sort_keys=True), flush=True)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except ValueError:
        # A malformed/drifting registration is a visible configuration block,
        # not an unbounded KeepAlive crash loop. Never print file contents.
        print(json.dumps({'stage':'host_service_configuration_blocked',
                          'controller_started':False}),flush=True)
        raise SystemExit(0)
