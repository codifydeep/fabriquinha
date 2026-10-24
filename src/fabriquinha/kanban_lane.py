"""S1 only: deterministic Docker lane using the unmodified Hermes dispatcher.

No model, GitHub mutation, product approval or deployment capability. This is
the execution seam qualification, not the future implementation of delivery.
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
UPSTREAM_COMMIT = 'e06df9c2eae6901f4c88f464e0ae6e753c0428b8'


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix('.pending')
    with os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), 'w') as stream:
        json.dump(value, stream, sort_keys=True)
    os.replace(temporary, path)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verdict(context, result):
    if context.get('mode') not in ('review', 'implementation'):
        raise ValueError('unknown execution phase')
    if not isinstance(result, dict) or set(result) != {'action', 'sha'}:
        raise ValueError('fixed fixture result required')
    if result['sha'] != context['sha']:
        raise ValueError('delivery changed')
    allowed = {'review', 'finish'}
    if context['mode'] == 'review':
        if context['actor'] == context['implementer']:
            raise ValueError('independent reviewer required')
        allowed = {'changes', 'approve'}
    if result['action'] not in allowed:
        raise ValueError('operation outside assigned phase')
    return result['action']


def native():
    from hermes_cli import kanban_db, kanban_db_connect, kanban_db_dispatch
    return kanban_db, kanban_db_connect, kanban_db_dispatch


def settings(path):
    value = json.loads(Path(path).read_text())
    if not re.fullmatch(r'sha256:[a-f0-9]{64}', value['image']):
        raise ValueError('cached image pinned by actual ID required')
    return value


class Lane:
    """Spawn callback only. Hermes owns claims, runs, retries and dependencies."""
    def __init__(self, configuration):
        self.path = Path(configuration).resolve()
        self.config = settings(self.path)
        self.children = []

    def spawn(self, task, workspace, *, board=None):
        kb, kbc, _ = native()
        with kbc.connect_closing() as conn:
            event = conn.execute('SELECT payload FROM task_events WHERE task_id=? AND '
                                 'run_id=? AND kind=? ORDER BY id DESC LIMIT 1',
                                 (task.id, task.current_run_id, 'claimed')).fetchone()
            source = json.loads(event[0]).get('source_status', 'ready')
        record = dict(task=task.id, run=task.current_run_id, actor=task.assignee,
                      mode='review' if source == 'review' else 'implementation',
                      workspace=workspace)
        folder = self.path.parent / 'runs' / str(task.current_run_id)
        record_path = folder / 'assignment.json'
        save(record_path, record)
        env = {key: os.environ[key] for key in ('PATH', 'PYTHONPATH', 'HERMES_HOME',
               'HERMES_KANBAN_DB', 'HERMES_KANBAN_BOARD') if key in os.environ}
        env['PYTHONDONTWRITEBYTECODE'] = '1'
        log = (folder / 'runner.log').open('wb')
        try:
            proc = subprocess.Popen([sys.executable, '-m', 'fabriquinha.kanban_lane',
                                     str(self.path), str(record_path)], env=env,
                                    stdin=subprocess.DEVNULL, stdout=log,
                                    stderr=subprocess.STDOUT, start_new_session=True)
        finally:
            log.close()
        self.children.append(proc)
        return proc.pid

    def tick(self):
        for child in self.children:
            child.poll()  # Reap our OS children; task lifecycle remains native.
        _, kbc, dispatch = native()
        with kbc.connect_closing() as conn:
            return dispatch.dispatch_once(conn, spawn_fn=self.spawn, max_spawn=2,
                max_in_progress=2, max_in_progress_per_profile=1)


def docker(*args, timeout=45):
    return subprocess.run(['docker', *args], capture_output=True, text=True,
                          timeout=timeout, check=True).stdout


def execute(configuration, assignment):
    config = settings(configuration)
    record = json.loads(Path(assignment).read_text())
    kb, kbc, _ = native()
    with kbc.connect_closing() as conn:
        task = kb.get_task(conn, record['task'])
        if task.current_run_id != record['run'] or task.status != 'running' or task.assignee != record['actor']:
            raise ValueError('stale native assignment')
        events = conn.execute('SELECT payload FROM task_events WHERE task_id=? AND '
                              'kind=? ORDER BY id DESC LIMIT 1',
                              (task.id, 'review_requested')).fetchone()
    record['implementer'] = json.loads(events[0])['implementer'] if events else record['actor']
    work = Path(record['workspace']).resolve()
    if not work.is_relative_to(Path(configuration).parent.resolve()):
        raise ValueError('fixture workspace outside isolated home')
    folder = Path(assignment).parent
    reviewing = record['mode'] == 'review'
    if reviewing:
        import shutil
        work = Path(shutil.copytree(work, folder / 'review-snapshot'))
        record['sha'] = sha(work / 'product.txt')
    sys.path.insert(0, str(ROOT / 'team-delivery-kit'))
    from docker_grouping import args as grouping
    name = 'delivery-kit-hermes-s1-run-' + str(record['run'])
    command = ['create', '--name', name, *grouping('fixture-worker', 'delivery-kit-hermes-s1'),
               '--network', 'none', '--read-only', '--user', '65534:65534',
               '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true',
               '--pids-limit', '32', '--memory', '64m', '--cpus', '0.5',
               '--tmpfs', '/tmp:rw,noexec,nosuid,size=8m',
               '--mount', f'type=bind,src={work},dst=/work' + (',readonly' if reviewing else ''),
               '--mount', f'type=bind,src={ROOT / "scripts/hermes_s1_worker.py"},dst=/probe.py,readonly',
               config['image'], 'python', '-B', '/probe.py', record['mode'],
               task.body or 'normal', str(kb.kanban_db_path())]
    container = docker(*command).strip()
    try:
        info = json.loads(docker('inspect', container))[0]
        policy = dict(image=info['Image'], user=info['Config']['User'],
                      network=info['HostConfig']['NetworkMode'], readonly=info['HostConfig']['ReadonlyRootfs'],
                      mounts=[dict(target=m['Destination'], writable=m['RW']) for m in info['Mounts']],
                      tmpfs=info['HostConfig']['Tmpfs'],
                      group=info['Config']['Labels']['com.docker.compose.project'])
        save(folder / 'sandbox.json', {**policy, 'container': container})
        mounts = {m['target']: m['writable'] for m in policy['mounts']}
        if (policy['image'] != config['image'] or policy['network'] != 'none' or
                not policy['readonly'] or policy['user'] != '65534:65534' or
                mounts != {'/work': not reviewing, '/probe.py': False} or
                set(policy['tmpfs']) != {'/tmp'}):
            raise ValueError('unexpected sandbox policy')
        output = docker('start', '-a', container, timeout=120)
        report = json.loads(output)
        save(folder / 'worker.json', report)
        if not all(report['isolation'].values()):
            raise ValueError('sandbox boundary failed')
        if not reviewing:
            record['sha'] = sha(work / 'product.txt')
        if reviewing and sha(Path(record['workspace']) / 'product.txt') != record['sha']:
            raise ValueError('author delivery changed during review')
        action = verdict(record, report['result'])
        with kbc.connect_closing() as conn:
            current = kb.get_task(conn, task.id)
            if current.current_run_id != record['run'] or current.status != 'running':
                raise ValueError('late result from superseded run')
            evidence = dict(synthetic=True, sha=record['sha'], fixture_only=True)
            if action == 'review':
                ok = kb.request_review(conn, task.id, reviewer='s1-reviewer',
                    summary='Deterministic S1 fixture', metadata=evidence, expected_run_id=record['run'])
            elif action == 'changes':
                ok, _ = kb.request_changes(conn, task.id, reason='Fixture needs version two',
                                            expected_run_id=record['run'])
            else:
                ok = kb.complete_task(conn, task.id, summary='S1 fixture completed',
                                      metadata=evidence, expected_run_id=record['run'])
            if not ok:
                raise ValueError('native transition rejected')
        save(folder / 'result.json', {**record, 'action': action, 'synthetic': True,
                                     'model_calls': 0, 'delivery_approval': False})
    finally:
        state = json.loads(docker('inspect', container))[0]
        if state['State']['Running']:
            docker('stop', '--time', '1', container)
        # Only this exact, stopped, archived probe. No volumes or images removed.
        (folder / 'container.log').write_text(docker('logs', container))
        docker('rm', container)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('configuration')
    parser.add_argument('assignment')
    options = parser.parse_args()
    execute(options.configuration, options.assignment)
