"""Evaluation-only broker: fixed offline probes, never arbitrary execution."""
import hmac
import hashlib
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import socket
import sqlite3
import subprocess
import threading
import time
import uuid
from docker_grouping import grouped_create
from contextlib import contextmanager

from test_runner_policy import unacceptable_output, validate_workspace_command
try:
    import handoff_runtime
except ImportError:
    from broker import handoff_runtime


def handoff_context():
    from types import SimpleNamespace
    return SimpleNamespace(**globals())

STATE = Path('/broker-state')
PREFIX = os.environ.get('BROKER_NAMESPACE', 'delivery-kit-eval')
if not re.fullmatch(r'delivery-kit-[a-z0-9-]{1,48}', PREFIX):
    raise ValueError('invalid broker namespace')
OWNER = PREFIX + '-broker-v1'
LOCK = threading.RLock()
IMAGE = os.environ['BROKER_WORKER_IMAGE']  # immutable image ID, operator configured
OFFLINE_IMAGE = os.environ.get('BROKER_VALIDATOR_IMAGE',IMAGE)
if 'BROKER_VALIDATOR_IMAGE' in os.environ and not re.fullmatch(r'sha256:[a-f0-9]{64}',OFFLINE_IMAGE):
    raise ValueError('immutable offline validator image required')
MODEL_NETWORK = os.environ.get('BROKER_MODEL_NETWORK', '')
TOKEN = ''
SESSIONS = {}


class RequiredTestMissing(ValueError):
    def __init__(self, names):
        self.names = names
        super().__init__('required tests missing: ' + ', '.join(names))


class DockerOperationTimeout(TimeoutError):
    def __init__(self,method,path):
        parts=path.split('?')[0].strip('/').split('/')
        resource=parts[0] if parts and parts[0] in ('containers','volumes','images','networks') else 'other'
        action=('create' if parts[-1]=='create' else 'start' if parts[-1]=='start'
                else 'delete' if method=='DELETE' else 'inspect' if method=='GET' else 'request')
        self.operation=resource+'_'+action
        super().__init__('Docker operation deadline')

class DockerConnection(http.client.HTTPConnection):
    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect('/var/run/docker.sock')


def docker(method, path, data=None):
    data = grouped_create(method, path, data, PREFIX)
    # Docker Desktop can spend >10s attaching an isolated worker's existing
    # volumes/network. One bounded create, not a repeated mutation after timeout.
    timeout = 30 if method=='POST' and path.split('?')[0]=='/containers/create' else 10
    conn = DockerConnection('localhost', timeout=timeout)
    try:
        conn.request(method, '/v1.45' + path,
                     None if data is None else json.dumps(data),
                     {'Content-Type': 'application/json'})
        response = conn.getresponse()
        body = response.read()
        if response.status not in (200, 201, 204, 304, 404):
            raise RuntimeError('Docker operation failed: ' + str(response.status))
        if response.status == 404:
            return None
        return json.loads(body) if body else {}
    except TimeoutError:
        raise DockerOperationTimeout(method,path) from None
    finally:
        conn.close()


def docker_stdout(name, include_stderr=False, limit=8192):
    conn = DockerConnection('localhost', timeout=10)
    try:
        conn.request('GET', '/v1.45/containers/' + name + '/logs?stdout=1&stderr='
                     + ('1' if include_stderr else '0'))
        response = conn.getresponse()
        data = response.read(limit + 1)
        if response.status != 200 or len(data) > limit:
            raise RuntimeError('validator output unavailable')
        chunks, index = [], 0
        while index < len(data):
            if index + 8 > len(data):
                raise RuntimeError('invalid Docker log frame')
            size = int.from_bytes(data[index + 4:index + 8], 'big')
            if data[index] not in ((1, 2) if include_stderr else (1,)) or index + 8 + size > len(data):
                raise RuntimeError('invalid validator stream')
            chunks.append(data[index + 8:index + 8 + size])
            index += 8 + size
        return b''.join(chunks).decode()
    finally:
        conn.close()


def verify_worker_image():
    """Fail before accepting tasks if the configured digest is not a Docker image ID."""
    if not re.fullmatch(r'sha256:[0-9a-f]{64}', IMAGE):
        raise ValueError('worker image must be an immutable Docker image ID')
    details = docker('GET', '/images/' + IMAGE + '/json')
    if not details or details.get('Id') != IMAGE:
        raise ValueError('configured worker image does not resolve to the exact Docker image ID')
    return IMAGE


@contextmanager
def db():
    con = sqlite3.connect(STATE / 'leases.sqlite', timeout=10)
    con.row_factory = sqlite3.Row
    try:
        with con:
            yield con
    finally:
        con.close()


def validate(payload):
    if not isinstance(payload, dict) or set(payload) != {'request_id', 'scenario'}:
        raise ValueError('only request_id and scenario allowed')
    if str(uuid.UUID(payload['request_id'])) != payload['request_id']:
        raise ValueError('canonical UUID required')
    if payload['scenario'] not in ('canary', 'lease'):
        raise ValueError('unknown fixed scenario')
    return payload


def native_scope(request_id):
    with db() as con:
        binding = con.execute('SELECT scope FROM native_bindings WHERE request_id=?', (request_id,)).fetchone()
        return binding['scope'] if binding else None


def native_mode(request_id):
    with db() as con:
        row = con.execute('SELECT g.mode FROM grants g JOIN native_bindings n USING(request_id) '
                          'WHERE g.request_id=?', (request_id,)).fetchone()
    return row['mode'] if row else None


def implementation_phase(issue_id):
    if not issue_id:
        return None
    try:
        import remediation_runtime_guard
    except ImportError:
        from broker import remediation_runtime_guard
    from types import SimpleNamespace
    remediation_phase = remediation_runtime_guard.phase(SimpleNamespace(
        db=db, PREFIX=PREFIX, OWNER=OWNER, issue_base=issue_base, docker=docker), issue_id)
    if remediation_phase:
        return remediation_phase
    try:
        import remediation_red_reference
    except ImportError:
        from broker import remediation_red_reference
    dependent_phase = remediation_red_reference.phase(SimpleNamespace(
        db=db, PREFIX=PREFIX, OWNER=OWNER, issue_base=issue_base, docker=docker), issue_id)
    if dependent_phase:
        return dependent_phase
    with db() as con:
        row = con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',
                          (issue_id,)).fetchone()
        if not row:
            return None
        route = json.loads(row[0])
        if not route.get('test_first'):
            return None
        try:
            import test_revision_review
        except ImportError:
            from broker import test_revision_review
        test_revision_review.initialize(con)
        revision = con.execute('SELECT state FROM test_revision_trials WHERE issue_id=?', (issue_id,)).fetchone()
        maintenance=con.execute('SELECT config FROM test_revision_trials WHERE issue_id=?',(issue_id,)).fetchone()
        if maintenance and json.loads(maintenance[0]).get('harness_maintenance_only'):
            return 'tests_only'  # Fixture maintenance can never unlock product writes.
        red = con.execute('SELECT 1 FROM test_first_red WHERE issue_id=?',
                          (issue_id,)).fetchone()
        if red and (not revision or json.loads(revision[0]).get('status') != 'approved'):
            return 'await_test_review'
        return 'implement_after_red' if red else 'tests_only'


def phase_editables(paths, route, phase, mode='implementation'):
    if mode != 'implementation':
        return []
    if not route or not route.get('test_first'):
        return list(paths)
    frozen = {'/workspace/' + name for name in route['test_first_files']}
    if phase == 'tests_only':
        return [path for path in paths if path in frozen]
    if phase == 'await_test_review':
        raise ValueError('independent new-test review required before implementation')
    if phase == 'implement_after_red':
        return [path for path in paths if path not in frozen]
    raise ValueError('test-first implementation phase missing')


def issue_base(issue_id):
    with db() as con:
        row = con.execute('SELECT * FROM issue_bases WHERE issue_id=?', (issue_id,)).fetchone()
    if not row:
        raise ValueError('issue has no registered Git base')
    volume = docker('GET', '/volumes/' + row['volume'])
    labels = {'delivery-kit.owner': OWNER, 'delivery-kit.issue-id': issue_id,
              'delivery-kit.base-sha': row['base_sha']}
    if not volume or any(volume.get('Labels', {}).get(k) != v for k, v in labels.items()):
        raise ValueError('issue base volume identity mismatch')
    return dict(row)


def register_issue_base(payload):
    if not isinstance(payload, dict) or set(payload) != {'issue_id', 'base_sha', 'volume', 'manifest_sha256'}:
        raise ValueError('invalid issue base registration')
    issue_id = payload['issue_id']
    if str(uuid.UUID(issue_id)) != issue_id or not re.fullmatch(r'[0-9a-f]{40}', payload['base_sha']) \
            or not re.fullmatch(r'[0-9a-f]{64}', payload['manifest_sha256']) \
            or payload['volume'] != PREFIX + '-base-' + issue_id:
        raise ValueError('invalid issue base identity')
    volume = docker('GET', '/volumes/' + payload['volume'])
    labels = {'delivery-kit.owner': OWNER, 'delivery-kit.issue-id': issue_id,
              'delivery-kit.base-sha': payload['base_sha']}
    if not volume or any(volume.get('Labels', {}).get(k) != v for k, v in labels.items()):
        raise ValueError('base volume labels mismatch')
    with LOCK, db() as con:
        prior = con.execute('SELECT * FROM issue_bases WHERE issue_id=?', (issue_id,)).fetchone()
        if prior and any(prior[k] != payload[k] for k in payload):
            raise ValueError('issue base is immutable')
        con.execute('INSERT OR IGNORE INTO issue_bases VALUES (?,?,?,?)',
                    (issue_id, payload['base_sha'], payload['volume'], payload['manifest_sha256']))
    return {'issue_id': issue_id, 'base_sha': payload['base_sha'], 'registered': True}


def register_issue_editables(payload):
    """Operator-only, immutable per-issue ACP edit allowlist."""
    if not isinstance(payload, dict) or set(payload) != {'issue_id', 'paths', 'test_command'}:
        raise ValueError('invalid editable registration')
    issue_id, paths = payload['issue_id'], payload['paths']
    test_command = payload['test_command']
    if str(uuid.UUID(issue_id)) != issue_id or not isinstance(paths, list) or not 0 < len(paths) <= 64 \
            or len(paths) != len(set(paths)) or any(
                not isinstance(path, str) or not re.fullmatch(r'/workspace/[A-Za-z0-9_./-]{1,220}', path)
                or any(part in ('', '.', '..') for part in path[len('/workspace/'):].split('/'))
                for path in paths):
        raise ValueError('invalid editable paths')
    validate_workspace_command(test_command)
    issue_base(issue_id)
    with LOCK, db() as con:
        existing = [row[0] for row in con.execute(
            'SELECT path FROM issue_editables WHERE issue_id=?', (issue_id,))]
        if existing and set(existing) != set(paths):
            raise ValueError('issue editable paths are immutable')
        for path in paths:
            con.execute('INSERT OR IGNORE INTO issue_editables VALUES (?,?)', (issue_id, path))
        prior_command = con.execute(
            'SELECT command FROM issue_test_commands WHERE issue_id=?', (issue_id,)).fetchone()
        if prior_command and prior_command[0] != test_command:
            raise ValueError('pinned test command is immutable')
        con.execute('INSERT OR IGNORE INTO issue_test_commands VALUES (?,?)',
                    (issue_id, test_command))
    return {'issue_id': issue_id, 'paths': sorted(paths), 'test_command': test_command}


def register_issue_requirements(payload):
    if not isinstance(payload, dict) or set(payload) != {'issue_id', 'required_tests'}:
        raise ValueError('invalid issue requirements')
    issue_id, names = payload['issue_id'], payload['required_tests']
    if str(uuid.UUID(issue_id)) != issue_id or not isinstance(names, list) or not 0 < len(names) <= 10 \
            or len(set(names)) != len(names) or any(not isinstance(n, str) or not re.fullmatch(r'test_[A-Za-z0-9_]{1,100}', n) for n in names):
        raise ValueError('invalid required test names')
    issue_base(issue_id)
    with LOCK, db() as con:
        existing = [row[0] for row in con.execute('SELECT test_name FROM issue_requirements WHERE issue_id=?', (issue_id,))]
        if existing and set(existing) != set(names):
            raise ValueError('issue acceptance is immutable')
        for name in names:
            con.execute('INSERT OR IGNORE INTO issue_requirements VALUES (?,?)', (issue_id, name))
    return {'issue_id': issue_id, 'required_tests': sorted(names)}


def seed_workspace(issue_id, scope, work_volume):
    base = issue_base(issue_id)
    try:
        import test_revision_review
    except ImportError:
        from broker import test_revision_review
    revision = test_revision_review.seed_source(handoff_context(), issue_id)
    mounts = [{'Type': 'volume', 'Source': base['volume'], 'Target': '/base', 'ReadOnly': True},
              {'Type': 'volume', 'Source': work_volume, 'Target': '/workspace'}]
    env = ['BASE_MANIFEST_SHA256=' + base['manifest_sha256']]
    if revision:
        mounts.append(revision['mount'])
        env.append('REVISION_SEED_JSON=' + json.dumps(revision['selection'], sort_keys=True))
    try:import helper_cleanup
    except ImportError:from broker import helper_cleanup
    name = helper_cleanup.new_name(handoff_context(),'seed',issue_id,scope)
    docker('POST', '/containers/create?name=' + name, {
        'Image': IMAGE, 'User': '10000:10000', 'Entrypoint': ['python'],
        'Cmd': ['/seed_workspace.py'], 'NetworkDisabled': True,
        'Env': env,
        'Labels': {'delivery-kit.owner': OWNER, 'delivery-kit.issue-id': issue_id},
        'HostConfig': {'ReadonlyRootfs': True, 'NetworkMode': 'none', 'CapDrop': ['ALL'],
                       'SecurityOpt': ['no-new-privileges'], 'Memory': 67108864,
                       'NanoCpus': 500000000, 'PidsLimit': 16,
                       'Mounts': mounts}})
    try:
        docker('POST', '/containers/' + name + '/start')
        deadline = time.time() + 20
        while time.time() < deadline:
            info = docker('GET', '/containers/' + name + '/json')
            if info and not info['State']['Running']:
                if info['State']['ExitCode'] != 0:
                    raise ValueError('issue workspace seed failed')
                return
            time.sleep(0.2)
        raise TimeoutError('workspace seed deadline')
    finally:
        try:import helper_cleanup
        except ImportError:from broker import helper_cleanup
        helper_cleanup.schedule(handoff_context(),name,issue_id)


def lock_workspace(issue_id, scope, work_volume, editable_paths):
    """Apply root-owned per-file permissions before any model prompt."""
    if not editable_paths or any(not path.startswith('/workspace/') for path in editable_paths):
        raise ValueError('workspace lockdown requires exact editable paths')
    base = issue_base(issue_id)
    import test_revision_review
    revision=test_revision_review.seed_source(handoff_context(),issue_id)
    repair={}
    if revision:
        selection=revision['selection']
        repair={name:{'bytes':size,'sha256':selection['test_sha256'][name]}
                for name,size in selection.get('repair_input_bytes',{}).items()
                if '/workspace/'+name in editable_paths}
    try:import helper_cleanup
    except ImportError:from broker import helper_cleanup
    name = helper_cleanup.new_name(handoff_context(),'lock',issue_id,scope)
    docker('POST', '/containers/create?name=' + name, {
        'Image': IMAGE, 'User': '0:0', 'Entrypoint': ['python'],
        'Cmd': ['/workspace_lockdown.py'], 'NetworkDisabled': True,
        'Env': ['WORKSPACE_ALLOWED_JSON=' + json.dumps(sorted(
            path.removeprefix('/workspace/') for path in editable_paths)),
            'WORKSPACE_REPAIR_INPUT_JSON='+json.dumps(repair,sort_keys=True)],
        'Labels': {'delivery-kit.owner': OWNER, 'delivery-kit.issue-id': issue_id},
        'HostConfig': {'ReadonlyRootfs': True, 'NetworkMode': 'none',
                       'CapDrop': ['ALL'], 'CapAdd': ['CHOWN', 'DAC_OVERRIDE'],
                       'SecurityOpt': ['no-new-privileges'], 'Memory': 67108864,
                       'NanoCpus': 500000000, 'PidsLimit': 16,
                       'Mounts': [{'Type': 'volume', 'Source': base['volume'],
                                   'Target': '/base', 'ReadOnly': True},
                                  {'Type': 'volume', 'Source': work_volume,
                                   'Target': '/workspace'}]}})
    try:
        docker('POST', '/containers/' + name + '/start')
        deadline = time.time() + 20
        while time.time() < deadline:
            info = docker('GET', '/containers/' + name + '/json')
            if info and not info['State']['Running']:
                if info['State']['ExitCode'] != 0:
                    raise ValueError('workspace lockdown failed')
                return
            time.sleep(0.2)
        raise TimeoutError('workspace lockdown deadline')
    finally:
        try:import helper_cleanup
        except ImportError:from broker import helper_cleanup
        helper_cleanup.schedule(handoff_context(),name,issue_id)


def review_snapshot(request_id):
    with db() as con:
        row = con.execute('SELECT n.agent_id,b.volume,b.source_task_id FROM native_bindings n '
                          'LEFT JOIN review_bindings b USING(request_id) '
                          'WHERE n.request_id=?', (request_id,)).fetchone()
    if not row:
        raise ValueError('review binding missing')
    settings = json.loads((STATE / 'native.json').read_text())
    if not row['volume']:
        if row['agent_id'] in settings.get('review_requires_snapshot', []):
            raise ValueError('review snapshot assignment missing')
        return None
    return row['volume'], row['source_task_id']


def tool_call_receipts(notifications):
    """Count distinct ACP tool starts, never storing arguments or output."""
    identifiers = set()
    for notification in notifications:
        if not isinstance(notification, dict) or notification.get('method') != 'session/update':
            continue
        params = notification.get('params') or {}
        update = params.get('update') or {} if isinstance(params, dict) else {}
        if isinstance(update, dict) and update.get('sessionUpdate') == 'tool_call':
            identifier = update.get('toolCallId')
            if isinstance(identifier, str) and identifier:
                identifiers.add(identifier)
    return len(identifiers)


def config(request_id, scenario):
    result = {
        'Image': IMAGE, 'User': '10000:10000',
        'Entrypoint': ['python'],
        'Cmd': {'canary': ['/probe.py'], 'acp': ['/acp_probe.py'],
                'acp-session': ['-c', 'import time; time.sleep(480)'],
                'lease': ['-c', 'import time; time.sleep(120)']}[scenario],
        'Env': ['HOME=/tmp', 'HERMES_HOME=/tmp/hermes', 'HERMES_CONTROLLER_DENIAL_MESSAGES=1'],
        'WorkingDir': '/tmp', 'NetworkDisabled': True,
        'Labels': {'delivery-kit.owner': OWNER, 'delivery-kit.request': request_id,
                   'com.docker.compose.project': PREFIX},
        'HostConfig': {'ReadonlyRootfs': True, 'NetworkMode': 'none',
                       'CapDrop': ['ALL'], 'SecurityOpt': ['no-new-privileges'],
                       'Memory': 268435456, 'NanoCpus': 1000000000, 'PidsLimit': 64,
                       'Tmpfs': {'/tmp': 'rw,nosuid,nodev,size=16m,mode=1777'},
                       'AutoRemove': False},
    }
    scope = native_scope(request_id)
    if scope and scenario == 'acp-session':
        volume = PREFIX + '-session-' + hashlib.sha256(scope.encode()).hexdigest()[:32]
        present = docker('GET', '/volumes/' + volume)
        if present is None:
            docker('POST', '/volumes/create', {'Name': volume, 'Labels': {'delivery-kit.owner': OWNER, 'delivery-kit.scope': scope}})
        elif present.get('Labels', {}).get('delivery-kit.scope') != scope or present.get('Labels', {}).get('delivery-kit.owner') != OWNER:
            raise ValueError('session volume identity mismatch')
        result['HostConfig']['Mounts'] = [{'Type': 'volume', 'Source': volume, 'Target': '/session-state'}]
        if native_mode(request_id) == 'implementation':
            with db() as con:
                bound = con.execute('SELECT issue_id FROM native_bindings WHERE request_id=?', (request_id,)).fetchone()
            if not bound or not bound['issue_id']:
                raise ValueError('implementation issue identity missing')
            work_volume = PREFIX + '-work-' + hashlib.sha256(scope.encode()).hexdigest()[:32]
            existing = docker('GET', '/volumes/' + work_volume)
            labels = {'delivery-kit.owner': OWNER, 'delivery-kit.scope': scope}
            if existing is None:
                docker('POST', '/volumes/create', {'Name': work_volume, 'Labels': labels})
            elif any(existing.get('Labels', {}).get(k) != v for k, v in labels.items()):
                raise ValueError('implementation volume identity mismatch')
            seed_workspace(bound['issue_id'], scope, work_volume)
            result['HostConfig']['Mounts'].append(
                {'Type': 'volume', 'Source': work_volume, 'Target': '/workspace'})
            try:import u3_controls_execution
            except ImportError:from broker import u3_controls_execution
            additive=u3_controls_execution.worker_config(handoff_context(),request_id,bound['issue_id'])
            if additive:
                result['Image']=additive['worker_image']
                result['Env'].append('DELIVERY_ADDITIVE_TEST_JSON='+json.dumps(additive['policy']))
            try:import surgical_recovery
            except ImportError:from broker import surgical_recovery
            surgical=surgical_recovery.worker_config(handoff_context(),request_id,bound['issue_id'])
            try:import driver_checkpoint_policy
            except ImportError:from broker import driver_checkpoint_policy
            driver=driver_checkpoint_policy.worker_config(handoff_context(),request_id,bound['issue_id'])
            try:import template_author_executor
            except ImportError:from broker import template_author_executor
            template=template_author_executor.worker_config(handoff_context(),request_id,bound['issue_id'])
            if template:
                if driver:raise ValueError('conflicting template/driver capabilities')
                driver=template
            if driver:
                if surgical:raise ValueError('conflicting surgical capabilities')
                image=docker('GET','/images/'+driver['worker_image']+'/json')
                if not image or image.get('Id')!=driver['worker_image']:
                    raise ValueError('qualified driver worker image missing')
                result['Image']=driver['worker_image']
                surgical=driver['surgical']
            if surgical:result['Env'].append('DELIVERY_SURGICAL_TEST_JSON='+json.dumps(surgical))
        elif native_mode(request_id) == 'review':
            try:import u3_delivery_review
            except ImportError:from broker import u3_delivery_review
            read_paths=u3_delivery_review.read_contract(handoff_context(),request_id)
            if read_paths:
                image=docker('GET','/containers/'+PREFIX+'-execution-broker-1/json')['Image']
                if not re.fullmatch(r'sha256:[0-9a-f]{64}',image):
                    raise ValueError('immutable qualified review worker required')
                result['Image']=image
                result['Env'].append('DELIVERY_REVIEW_READ_PATHS_JSON='+json.dumps(read_paths))
            assignment = review_snapshot(request_id)
            if assignment:
                snapshot_volume, source_task_id = assignment
                frozen = docker('GET', '/volumes/' + snapshot_volume)
                if not frozen or frozen.get('Labels', {}).get('delivery-kit.owner') != OWNER or frozen.get('Labels', {}).get('delivery-kit.source-task') != source_task_id:
                    raise ValueError('review snapshot identity mismatch')
                result['HostConfig']['Mounts'].append(
                    {'Type': 'volume', 'Source': snapshot_volume, 'Target': '/delivery',
                     'ReadOnly': True})
        elif native_mode(request_id) == 'planning':
            try:
                import test_revision_review
            except ImportError:
                from broker import test_revision_review
            try:
                import qa_artifacts
            except ImportError:
                from broker import qa_artifacts
            qa_mounts = qa_artifacts.mounts(handoff_context(), request_id)
            result['HostConfig']['Mounts'].extend(qa_mounts or test_revision_review.planning_mounts(handoff_context(), request_id))
        if MODEL_NETWORK:
            result['NetworkDisabled'] = False
            result['HostConfig']['NetworkMode'] = MODEL_NETWORK
    return result


def remove_owned(name, request_id):
    session = SESSIONS.pop(request_id, None)
    if session:
        session.close()
    info = docker('GET', '/containers/' + name + '/json')
    if info is None:
        return
    labels = info['Config'].get('Labels', {})
    if labels.get('delivery-kit.owner') != OWNER or labels.get('delivery-kit.request') != request_id:
        raise RuntimeError('container identity mismatch')
    docker('DELETE', '/containers/' + info['Id'] + '?force=true')


def tick():
    try:import worker_creation_intent
    except ImportError:from broker import worker_creation_intent
    worker_creation_intent.reconcile(handoff_context())
    with LOCK, db() as con:
        # A durable close intent precedes Docker deletion. Reconcile a crash or
        # failed acknowledgment without treating an unexplained disappearance
        # as completion. This receipt closes execution, never approves delivery.
        for row in con.execute("SELECT * FROM leases WHERE status='closing'").fetchall():
            remove_owned(row['name'], row['request_id'])
            con.execute("UPDATE leases SET status='closed' WHERE request_id=? AND status='closing'",
                        (row['request_id'],))
        for row in con.execute("SELECT * FROM leases WHERE status='running'").fetchall():
            binding = con.execute('SELECT task_id,agent_id FROM native_bindings WHERE request_id=?',
                                  (row['request_id'],)).fetchone()
            if binding:
                from native import task_record
                try:
                    settings = json.loads((STATE / 'native.json').read_text())
                    task = task_record(settings, binding['task_id'], binding['agent_id'])
                except (OSError, ValueError, KeyError, json.JSONDecodeError):
                    task = None  # transient control-plane failure never cancels a live task
                if task and task.get('status') == 'cancelled':
                    remove_owned(row['name'], row['request_id'])
                    con.execute('UPDATE leases SET status=? WHERE request_id=?',
                                ('cancelled', row['request_id']))
                    continue
            info = docker('GET', '/containers/' + row['name'] + '/json')
            if info is None:
                status = 'lost'
            elif not info['State']['Running']:
                status = 'passed' if info['State']['ExitCode'] == 0 and row['scenario'] in ('canary', 'acp') else 'failed'
            elif time.time() >= row['deadline']:
                status = 'expired'
            else:
                continue
            remove_owned(row['name'], row['request_id'])
            con.execute('UPDATE leases SET status=? WHERE request_id=?', (status, row['request_id']))


def submit(payload, trusted_acp=False):
    if not trusted_acp:
        payload = validate(payload)
    request_id, scenario = payload['request_id'], payload['scenario']
    with LOCK, db() as con:
        previous = con.execute('SELECT * FROM leases WHERE request_id=?', (request_id,)).fetchone()
        if previous:
            if previous['scenario'] != scenario:
                raise ValueError('idempotency conflict')
            return dict(previous)
        if con.execute("SELECT count(*) FROM leases WHERE status IN ('creating','running')").fetchone()[0] >= 2:
            raise ValueError('capacity exhausted')
        name = PREFIX + '-job-' + request_id
        con.execute('INSERT INTO leases VALUES (?,?,?,?,?)',
                    (request_id, scenario, name, 'creating', time.time() +
                     (420 if scenario == 'acp-session' else 45)))
        con.commit()  # durable intent before Docker side effect
        create_intent=False
        starting=False
        try:
            expected=config(request_id, scenario)
            try:import worker_creation_intent
            except ImportError:from broker import worker_creation_intent
            worker_creation_intent.record(con,request_id,expected)
            con.commit()  # immutable payload before the possibly delayed create
            create_intent=True
            docker('POST', '/containers/create?name=' + name, expected)
            worker_creation_intent.start_intent(con,request_id)
            con.commit()  # a lost start acknowledgement cannot authorize repost
            starting=True
            docker('POST', '/containers/' + name + '/start')
            worker_creation_intent.started(con,request_id)
            con.execute("UPDATE leases SET status='running' WHERE request_id=?", (request_id,))
        except Exception as error:
            if isinstance(error,DockerOperationTimeout) and (
                    create_intent and error.operation=='containers_create' or
                    starting and error.operation=='containers_start'):
                if starting:worker_creation_intent.start_uncertain(con,request_id)
                else:worker_creation_intent.uncertain(con,request_id)
                con.execute('INSERT INTO broker_errors VALUES (?,?,?,?)',
                    (request_id,'worker_submit','bootstrap:'+failure_category(error),time.time()))
                con.commit()  # unknown outcome is observed, not blindly deleted/reposted
                raise
            # Preserve primary failure and close intent before slow cleanup can fail.
            con.execute("UPDATE leases SET status='closing' WHERE request_id=?", (request_id,))
            con.execute('INSERT INTO broker_errors VALUES (?,?,?,?)',
                        (request_id, 'worker_submit', 'bootstrap:' + failure_category(error),
                         time.time()))
            con.commit()
            try:
                remove_owned(name, request_id)
                con.execute("UPDATE leases SET status='failed' WHERE request_id=?", (request_id,))
                con.commit()
            except Exception as cleanup_error:
                con.execute('INSERT INTO broker_errors VALUES (?,?,?,?)',
                    (request_id,'bootstrap_cleanup',failure_category(cleanup_error),time.time()))
                con.commit() # watchdog reconciles closing; primary error is not replaced
            raise
        return dict(con.execute('SELECT * FROM leases WHERE request_id=?', (request_id,)).fetchone())


def issue_grant(payload):
    if not isinstance(payload, dict) or set(payload) != {'task_id', 'attempt', 'mode'}:
        raise ValueError('invalid grant fields')
    if str(uuid.UUID(payload['task_id'])) != payload['task_id']:
        raise ValueError('invalid task identity')
    if type(payload['attempt']) is not int or payload['attempt'] < 1:
        raise ValueError('invalid attempt')
    if payload['mode'] not in ('implementation', 'review', 'planning'):
        raise ValueError('invalid mode')
    with LOCK, db() as con:
        previous = con.execute('SELECT * FROM grants WHERE task_id=? ORDER BY attempt DESC LIMIT 1', (payload['task_id'],)).fetchone()
        if previous and payload['attempt'] <= previous['attempt']:
            raise ValueError('attempt must advance')
        if previous:
            lease = con.execute('SELECT * FROM leases WHERE request_id=?', (previous['request_id'],)).fetchone()
            if lease and lease['status'] in ('creating', 'running'):
                raise ValueError('previous execution not fenced')
        token = secrets.token_hex(32)
        request_id = str(uuid.uuid4())
        con.execute('INSERT INTO grants VALUES (?,?,?,?,?,?,?)',
                    (hashlib.sha256(token.encode()).hexdigest(), payload['task_id'],
                     payload['attempt'], payload['mode'], request_id, time.time() + 480, 0))
        return {'capability': token, 'request_id': request_id, **payload}


def native_grant(payload):
    from native import task_binding
    if set(payload) != {'task_id', 'agent_id'}:
        raise ValueError('native identity only')
    settings = json.loads((STATE / 'native.json').read_text())
    binding = task_binding(settings, **payload)
    if not binding['issue_id']:
        raise ValueError('native task missing issue identity')
    try:
        try:import u3_delivery_review
        except ImportError:from broker import u3_delivery_review
    except ImportError:
        from broker import u3_delivery_review
    coverage_review = binding['mode'] == 'review' and u3_delivery_review.authorize_binding(handoff_context(), binding)
    if binding['mode'] != 'planning' and not coverage_review:
        issue_base(binding['issue_id'])
    if binding['mode'] == 'implementation':
        with db() as con:
            enabled_schema = con.execute("SELECT 1 FROM sqlite_master WHERE name='task_contracts'").fetchone()
        if enabled_schema:
            handoff_runtime.bind_contract(handoff_context(), binding['task_id'], binding['issue_id'])
    if payload['agent_id'] in settings.get('review_requires_snapshot', []) and not coverage_review:
        auto_prepare_review(settings, payload['task_id'], payload['agent_id'])
    with LOCK, db() as con:
        busy = con.execute("SELECT 1 FROM native_bindings n JOIN leases l USING(request_id) WHERE n.scope=? AND l.status IN ('creating','running')", (binding['scope'],)).fetchone()
        if busy:
            raise ValueError('scope still owned by active execution')
        attempt = con.execute('SELECT COALESCE(max(attempt),0)+1 FROM grants WHERE task_id=?', (binding['task_id'],)).fetchone()[0]
        grant = issue_grant({'task_id': binding['task_id'], 'attempt': attempt, 'mode': binding['mode']})
        con.execute('INSERT INTO native_bindings VALUES (?,?,?,?,?)', (grant['request_id'], binding['task_id'], binding['agent_id'], binding['scope'], binding['issue_id']))
        if coverage_review or binding['agent_id'] in settings.get('review_requires_snapshot', []):
            assignment = con.execute('SELECT source_task_id,volume FROM review_assignments WHERE review_agent_id=?',
                                     (binding['agent_id'],)).fetchone()
            if not assignment:
                raise ValueError('review handoff assignment absent')
            con.execute('INSERT INTO review_bindings VALUES (?,?,?)',
                        (grant['request_id'], assignment['source_task_id'], assignment['volume']))
        return grant


def model_output_limit(run):
    result = run.get('result')
    output = result.get('output') if isinstance(result, dict) else None
    return (isinstance(output, str) and 'No visible answer was produced.' in output
            and 'output-token limit' in output)


def auto_prepare_review(settings, review_task_id, reviewer_id):
    """Narrow handoff on a Multica issue wakeup, not a second scheduler."""
    from native import task_record, issue_task_runs
    review_task = task_record(settings, review_task_id, reviewer_id)
    issue_id = review_task.get('issue_id')
    if not issue_id or review_task.get('status') != 'running':
        raise ValueError('review must be a running issue task')
    runs = issue_task_runs(settings, issue_id)
    sources = [run for run in runs if run.get('status') == 'completed'
               and settings['agents'].get(run.get('agent_id')) == 'implementation']
    if not sources:
        raise ValueError('review requires a completed implementation')
    sources.sort(key=lambda run: (run.get('completed_at') or '', run['id']), reverse=True)
    if len(sources) > 1 and sources[0].get('completed_at') == sources[1].get('completed_at'):
        raise ValueError('ambiguous latest implementation')
    if model_output_limit(sources[0]):
        with db() as con:
            con.execute('INSERT OR REPLACE INTO review_incidents VALUES (?,?,?,?)',
                        (review_task_id, 'implementation_model_output_limit',
                         'infrastructure_model_limit', time.time()))
        raise ValueError('implementation has no reviewable model output')
    source_id = sources[0]['id']
    with db() as con:
        if con.execute("SELECT 1 FROM sqlite_master WHERE name='delivery_routes'").fetchone():
            route = con.execute('SELECT 1 FROM delivery_routes WHERE issue_id=?', (issue_id,)).fetchone()
            if route:
                pending = [json.loads(row[0]) for row in con.execute(
                    'SELECT data FROM delivery_handoffs WHERE issue_id=?', (issue_id,))]
                matching = [item for item in pending if item.get('target') == reviewer_id
                            and (item.get('wakeup_id') == review_task.get('wakeup_id')
                                 or ('DELIVERY_HANDOFF ' + item.get('dispatch_marker', '!'))
                                 in (review_task.get('handoff_note') or ''))]
                if len(matching) != 1 or matching[0]['source_task'] != source_id:
                    raise ValueError('review handoff is stale or unregistered')
    snapshot_submission({'task_id': source_id})
    assign_review({'source_task_id': source_id, 'review_agent_id': reviewer_id})


def snapshot_submission(payload, *, diagnostic=False):
    """Freeze one completed native implementation into a controller-owned volume."""
    if not isinstance(payload, dict) or set(payload) != {'task_id'}:
        raise ValueError('snapshot requires task identity only')
    task_id = payload['task_id']
    if str(uuid.UUID(task_id)) != task_id:
        raise ValueError('invalid snapshot task')
    from native import task_record, issue_task_runs
    with LOCK, db() as con:
        table = 'failed_execution_snapshots' if diagnostic else 'snapshots'
        if diagnostic:
            con.execute('CREATE TABLE IF NOT EXISTS failed_execution_snapshots('
                        'task_id TEXT PRIMARY KEY,volume TEXT,status TEXT)')
        previous = con.execute(f'SELECT status,volume FROM {table} WHERE task_id=?', (task_id,)).fetchone()
        if previous:
            if previous['status'] == 'complete':
                return {'task_id': task_id, 'status': 'complete', 'volume': previous['volume']}
            if previous['status'] != 'creating':
                raise ValueError('snapshot requires a new submission revision')
        row = con.execute('SELECT n.request_id,n.agent_id,n.scope,g.mode,l.status '
                          'FROM native_bindings n JOIN grants g USING(request_id) '
                          'JOIN leases l USING(request_id) WHERE n.task_id=? '
                          'ORDER BY g.attempt DESC LIMIT 1', (task_id,)).fetchone()
        allowed_statuses = ('expired', 'failed', 'closed') if diagnostic else ('closed',)
        if not row or row['mode'] != 'implementation' or row['status'] not in allowed_statuses:
            raise ValueError('no completed implementation lease')
        settings = json.loads((STATE / 'native.json').read_text())
        task = task_record(settings, task_id, row['agent_id'])
        if task.get('status') != ('failed' if diagnostic else 'completed'):
            raise ValueError('native implementation not completed')
        if not task.get('issue_id'):
            raise ValueError('native implementation issue missing')
        runs = [run for run in issue_task_runs(settings, task['issue_id'])
                if run.get('agent_id') == row['agent_id']]
        if not runs or max(runs, key=lambda run: (run.get('created_at') or '', run['id']))['id'] != task_id:
            raise ValueError('snapshot source is superseded')
        base = handoff_runtime.task_base(handoff_context(), task['issue_id'], task_id)
        active = con.execute("SELECT 1 FROM native_bindings n JOIN leases l USING(request_id) "
                             "WHERE n.scope=? AND l.status IN ('creating','running')", (row['scope'],)).fetchone()
        if active:
            raise ValueError('implementation scope still active')
        work_volume = PREFIX + '-work-' + hashlib.sha256(row['scope'].encode()).hexdigest()[:32]
        source = docker('GET', '/volumes/' + work_volume)
        if not source or source.get('Labels', {}).get('delivery-kit.scope') != row['scope'] or source.get('Labels', {}).get('delivery-kit.owner') != OWNER:
            raise ValueError('workspace volume identity mismatch')
        snapshot_volume = PREFIX + ('-failed-snapshot-' if diagnostic else '-snapshot-') + task_id
        volume = docker('GET', '/volumes/' + snapshot_volume)
        if volume and (not previous or volume.get('Labels', {}).get('delivery-kit.source-task') != task_id
                       or volume.get('Labels', {}).get('delivery-kit.owner') != OWNER):
            raise ValueError('untracked snapshot volume exists')
        con.execute(f'INSERT OR IGNORE INTO {table} VALUES (?,?,?)', (task_id, snapshot_volume, 'creating'))
        con.commit()
        name = PREFIX + ('-failed-snapshot-job-' if diagnostic else '-snapshot-job-') + task_id
        try:
            old_job = docker('GET', '/containers/' + name + '/json')
            if old_job:
                if old_job['Config'].get('Labels', {}).get('delivery-kit.source-task') != task_id:
                    raise ValueError('snapshot job identity mismatch')
                docker('DELETE', '/containers/' + old_job['Id'] + '?force=true')
            docker('POST', '/volumes/create', {'Name': snapshot_volume,
                'Labels': {'delivery-kit.owner': OWNER, 'delivery-kit.source-task': task_id,
                           **({'delivery-kit.diagnostic-only': 'true'} if diagnostic else {})}})
            docker('POST', '/containers/create?name=' + name, {
                'Image': IMAGE, 'User': '10000:10000', 'Entrypoint': ['python'],
                'Cmd': ['/snapshot_copy.py'], 'WorkingDir': '/', 'NetworkDisabled': True,
                'Env': ['SNAPSHOT_RESUME=' + ('1' if previous else '0')],
                'Labels': {'delivery-kit.owner': OWNER, 'delivery-kit.source-task': task_id,
                           'com.docker.compose.project': PREFIX},
                'HostConfig': {'ReadonlyRootfs': True, 'NetworkMode': 'none',
                               'CapDrop': ['ALL'], 'SecurityOpt': ['no-new-privileges'],
                               'Memory': 67108864, 'NanoCpus': 500000000, 'PidsLimit': 16,
                               'Mounts': [{'Type': 'volume', 'Source': work_volume,
                                           'Target': '/workspace', 'ReadOnly': True},
                                          {'Type': 'volume', 'Source': base['volume'],
                                           'Target': '/base', 'ReadOnly': True},
                                          {'Type': 'volume', 'Source': snapshot_volume,
                                           'Target': '/snapshot'}]}})
            docker('POST', '/containers/' + name + '/start')
            deadline = time.time() + 20
            while time.time() < deadline:
                info = docker('GET', '/containers/' + name + '/json')
                if info and not info['State']['Running']:
                    if info['State']['ExitCode'] != 0:
                        try:
                            failure = json.loads(docker_stdout(name))
                        except (ValueError, RuntimeError):
                            failure = None
                        missing = failure.get('missing') if isinstance(failure, dict) else None
                        editable = {row[0].removeprefix('/workspace/') for row in
                                    con.execute('SELECT path FROM issue_editables WHERE issue_id=?',
                                                (task['issue_id'],))}
                        if (isinstance(failure, dict)
                                and failure.get('error') == 'required_artifact_missing'
                                and isinstance(missing, list) and missing
                                and all(isinstance(item, str) for item in missing)
                                and set(missing) <= editable):
                            raise ValueError('required artifact missing: ' + ', '.join(missing))
                        raise RuntimeError('snapshot copy rejected artifact')
                    con.execute(f"UPDATE {table} SET status='complete' WHERE task_id=?", (task_id,))
                    con.commit()  # Release the writer before durable cleanup uses its own transaction.
                    return {'task_id': task_id, 'status': 'complete', 'volume': snapshot_volume}
                time.sleep(0.2)
            raise TimeoutError('snapshot copy deadline')
        except Exception as error:
            con.execute(f"UPDATE {table} SET status='failed' WHERE task_id=?", (task_id,))
            con.execute('INSERT OR REPLACE INTO snapshot_diagnostics VALUES (?,?)',
                        (task_id, str(error)[:240]))
            con.commit()  # Preserve failure despite the caller's exception.
            raise
        finally:
            try:import helper_cleanup
            except ImportError:from broker import helper_cleanup
            helper_cleanup.schedule(handoff_context(), name, task_id)


def capture_test_first_red(payload, *, _failed_checkpoint=None):
    """Freeze a completed tests-only task, then run pinned Red off-network."""
    if not isinstance(payload, dict) or set(payload) != {'task_id'}:
        raise ValueError('test-first requires task identity only')
    task_id = payload['task_id']
    if str(uuid.UUID(task_id)) != task_id:
        raise ValueError('invalid test-first task')
    from native import task_record, issue_task_runs
    from portable_contract import IMAGE as PINNED_IMAGE
    from test_runner_policy import validate_argv
    from test_first_protocol import assess_red, save_red_rejection
    with LOCK, db() as con:
        prior = con.execute('SELECT receipt FROM test_first_red WHERE task_id=?',
                            (task_id,)).fetchone()
        if prior:
            return json.loads(prior['receipt'])
        row = con.execute('SELECT n.issue_id,n.request_id,n.agent_id,n.scope,g.mode,l.status '
                          'FROM native_bindings n JOIN grants g USING(request_id) '
                          'JOIN leases l USING(request_id) WHERE n.task_id=? '
                          'ORDER BY g.attempt DESC LIMIT 1', (task_id,)).fetchone()
        if not row or row['mode'] != 'implementation' or row['status'] != 'closed':
            raise ValueError('test-first requires completed implementation lease')
        configured = con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',
                                 (row['issue_id'],)).fetchone()
        route = json.loads(configured[0]) if configured else {}
        if (route.get('test_first') is not True or not route.get('enabled')
                or route.get('author') != row['agent_id']):
            raise ValueError('test-first route is not enabled for this author')
        if con.execute('SELECT 1 FROM test_first_red WHERE issue_id=?',
                       (row['issue_id'],)).fetchone():
            raise ValueError('test-first already captured for issue')
        settings = json.loads((STATE / 'native.json').read_text())
        task = task_record(settings, task_id, row['agent_id'])
        runs = [r for r in issue_task_runs(settings, row['issue_id'])
                if r.get('agent_id') == row['agent_id']]
        checkpoint_volume = None
        if _failed_checkpoint is not None:
            import failed_test_checkpoint
            checkpoint_volume = failed_test_checkpoint.validate_capture(
                handoff_context(), con, row, _failed_checkpoint, route)
        if (task.get('status') != ('failed' if checkpoint_volume else 'completed')
                or task.get('issue_id') != row['issue_id']
                or not runs or max(runs, key=lambda r: (r.get('created_at') or '', r['id']))['id'] != task_id):
            raise ValueError('test-first source is stale or incomplete')
        if con.execute("SELECT 1 FROM native_bindings n JOIN leases l USING(request_id) "
                       "WHERE n.scope=? AND l.status IN ('creating','starting','running','closing')",
                       (row['scope'],)).fetchone():
            raise ValueError('test-first source workspace remains active')
        base = handoff_runtime.task_base(handoff_context(), row['issue_id'], task_id)
        work_volume = PREFIX + '-work-' + hashlib.sha256(row['scope'].encode()).hexdigest()[:32]
        work = docker('GET', '/volumes/' + work_volume)
        if (not work or work.get('Labels', {}).get('delivery-kit.owner') != OWNER
                or work.get('Labels', {}).get('delivery-kit.scope') != row['scope']):
            raise ValueError('test-first workspace identity mismatch')
        volume = PREFIX + '-test-first-' + task_id
        labels = {'delivery-kit.owner': OWNER, 'delivery-kit.test-first-task': task_id}
        existing = docker('GET', '/volumes/' + volume)
        if existing and any(existing.get('Labels', {}).get(k) != v for k, v in labels.items()):
            raise ValueError('foreign test-first volume')
        if not existing:
            docker('POST', '/volumes/create', {'Name': volume, 'Labels': labels})
        job = PREFIX + '-test-first-copy-' + task_id
        old = docker('GET', '/containers/' + job + '/json')
        if old:
            if old['Config'].get('Labels', {}).get('delivery-kit.test-first-task') != task_id:
                raise ValueError('foreign test-first copy job')
            docker('DELETE', '/containers/' + old['Id'] + '?force=true')
        docker('POST', '/containers/create?name=' + job, {
            'Image': IMAGE if checkpoint_volume else OFFLINE_IMAGE,
            'User': '10000:10000', 'Entrypoint': ['python'],
            'Cmd': ['/failed_test_checkpoint_copy.py' if checkpoint_volume else '/test_first_copy.py'],
            'NetworkDisabled': True,
            'Env': ['TEST_FIRST_RESUME=' + ('1' if existing else '0')],
            'Labels': labels | {'com.docker.compose.project': PREFIX},
            'HostConfig': {'ReadonlyRootfs': True, 'NetworkMode': 'none',
                           'CapDrop': ['ALL'], 'SecurityOpt': ['no-new-privileges'],
                           'Memory': 134217728, 'NanoCpus': 500000000, 'PidsLimit': 16,
                           'Tmpfs': {'/tmp': 'rw,nosuid,nodev,size=32m,mode=1777'},
                           'Mounts': [{'Type': 'volume', 'Source': base['volume'],
                                       'Target': '/base', 'ReadOnly': True},
                                  {'Type': 'volume', 'Source': checkpoint_volume or work_volume,
                                       'Target': '/workspace', 'ReadOnly': True},
                                      {'Type': 'volume', 'Source': volume,
                                       'Target': '/snapshot'}]}})
        try:
            docker('POST', '/containers/' + job + '/start')
            deadline = time.time() + 25
            while time.time() < deadline:
                state = docker('GET', '/containers/' + job + '/json')['State']
                if not state['Running']:
                    if state['ExitCode']:
                        from test_first_protocol import snapshot_rejection_error
                        try:
                            rejection=json.loads(docker_stdout(job))
                        except (ValueError,TypeError):
                            rejection={}
                        message=snapshot_rejection_error(rejection)
                        if rejection.get('kind')=='rejected_snapshot':
                            diagnostic={**rejection,'issue_id':row['issue_id'],'task_id':task_id}
                            if rejection.get('category') == 'empty_new_test' and len(rejection.get('files', {})) == 1:
                                try:
                                    from native import task_messages
                                    from test_author_activity import summarize
                                    name = next(iter(rejection['files']))
                                    diagnostic['author_activity'] = summarize(
                                        task_messages(settings, task_id), '/workspace/' + name)
                                except Exception as error:
                                    diagnostic['author_activity'] = {
                                        'status': 'evidence_unavailable', 'category': type(error).__name__}
                            directory=STATE/'test-first-incidents';directory.mkdir(exist_ok=True)
                            path=directory/(task_id+'.json')
                            if not path.exists():
                                with path.open('x') as output:json.dump(diagnostic,output,sort_keys=True)
                            elif json.loads(path.read_text()) != diagnostic:
                                raise ValueError('test-first incident identity drift')
                        raise ValueError(message)
                    prepared = json.loads(docker_stdout(job))
                    break
                time.sleep(.2)
            else:
                raise TimeoutError('test-first copy deadline')
        finally:
            info = docker('GET', '/containers/' + job + '/json')
            if info and info['Config'].get('Labels', {}).get('delivery-kit.test-first-task') == task_id:
                docker('DELETE', '/containers/' + info['Id'] + '?force=true')
        if (not isinstance(prepared, dict) or not re.fullmatch(r'[0-9a-f]{64}',
                prepared.get('manifest_sha256', '')) or
                not PINNED_IMAGE.fullmatch(prepared.get('test_image', ''))):
            raise ValueError('invalid test-first copy receipt')
        runner = PREFIX + '-test-first-red-' + task_id
        import harness_qualification
        harness_qualification.capture(handoff_context(),con,row['issue_id'],task_id,volume,prepared)
        command = prepared['command']
        validate_argv(command, prepared['test_roots'])
        old_runner = docker('GET', '/containers/' + runner + '/json')
        if old_runner:
            if old_runner['Config'].get('Labels', {}).get('delivery-kit.test-first-task') != task_id:
                raise ValueError('foreign test-first Red runner')
            # A retry is safe: frozen input is read-only and the runner has no
            # network, credentials or side-effectful host mount.
            docker('DELETE', '/containers/' + old_runner['Id'] + '?force=true')
        docker('POST', '/containers/create?name=' + runner, {
            'Image': prepared['test_image'], 'User': '10000:10000',
            'Entrypoint': [command[0]], 'Cmd': command[1:], 'WorkingDir': '/delivery',
            'NetworkDisabled': True, 'Env': ['PYTHONDONTWRITEBYTECODE=1'],
            'Labels': labels | {'com.docker.compose.project': PREFIX},
            'HostConfig': {'ReadonlyRootfs': True, 'NetworkMode': 'none',
                           'CapDrop': ['ALL'], 'SecurityOpt': ['no-new-privileges'],
                           'Memory': 268435456, 'NanoCpus': 1000000000, 'PidsLimit': 96,
                           'Mounts': [{'Type': 'volume', 'Source': volume,
                                       'Target': '/delivery', 'ReadOnly': True}],
                           'Tmpfs': {'/tmp': 'rw,nosuid,nodev,size=32m,mode=1777'}}})
        try:
            docker('POST', '/containers/' + runner + '/start')
            deadline = time.time() + 120
            while time.time() < deadline:
                state = docker('GET', '/containers/' + runner + '/json')['State']
                if not state['Running']:
                    output = docker_stdout(runner, include_stderr=True, limit=65536)
                    try:
                        red = assess_red(state['ExitCode'], output, prepared)
                    except ValueError as failure:
                        save_red_rejection(STATE / 'test-first-incidents', row['issue_id'],
                                           task_id, state['ExitCode'], output, prepared,
                                           str(failure))
                        raise
                    trial_row = con.execute('SELECT config FROM test_revision_trials WHERE issue_id=?',
                        (row['issue_id'],)).fetchone() if con.execute("SELECT 1 FROM sqlite_master WHERE name='test_revision_trials'").fetchone() else None
                    trial = json.loads(trial_row[0]) if trial_row else {}
                    if (trial.get('seed_previous_tests') is True
                            and red['test_sha256'] == trial['old_red']['red']['test_sha256']):
                        save_red_rejection(STATE / 'test-first-incidents', row['issue_id'],
                            task_id, state['ExitCode'], output, prepared,
                            'sponsored repair requires changed NEW-test snapshot')
                        raise ValueError('sponsored repair requires changed NEW-test snapshot')
                    receipt = {'issue_id': row['issue_id'], 'task_id': task_id,
                               'scope': row['scope'], 'volume': volume,
                               'red': red, 'captured_at': time.time()}
                    con.execute('INSERT INTO test_first_red VALUES (?,?,?,?,?)',
                                (row['issue_id'], task_id, row['scope'], volume,
                                 json.dumps(receipt, sort_keys=True)))
                    return receipt
                time.sleep(.2)
            raise TimeoutError('test-first Red deadline')
        finally:
            info = docker('GET', '/containers/' + runner + '/json')
            if info and info['Config'].get('Labels', {}).get('delivery-kit.test-first-task') == task_id:
                docker('DELETE', '/containers/' + info['Id'] + '?force=true')


def verify_test_first_green(volume, task_id, red_receipt):
    """Compare new test bytes inside the immutable final delivery volume."""
    hashes = red_receipt['red']['test_sha256']
    red_volume = red_receipt['volume']
    manifest_sha = red_receipt['red']['manifest_sha256']
    if (not isinstance(hashes, dict) or not hashes or len(hashes) > 64
            or any(not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_./-]{1,220}', name)
                   or not isinstance(digest, str) or not re.fullmatch(r'[a-f0-9]{64}', digest)
                   for name, digest in hashes.items())):
        raise ValueError('invalid frozen Red test hashes')
    if (not isinstance(red_volume, str) or not red_volume.startswith(PREFIX + '-test-first-')
            or not re.fullmatch(r'[a-f0-9]{64}', manifest_sha)):
        raise ValueError('invalid Red snapshot identity')
    name = PREFIX + '-test-first-verify-' + task_id
    labels = {'delivery-kit.owner': OWNER, 'delivery-kit.source-task': task_id,
              'com.docker.compose.project': PREFIX}
    old = docker('GET', '/containers/' + name + '/json')
    if old:
        if old['Config'].get('Labels', {}).get('delivery-kit.source-task') != task_id:
            raise ValueError('foreign test-first Green verifier')
        docker('DELETE', '/containers/' + old['Id'] + '?force=true')
    docker('POST', '/containers/create?name=' + name, {
        'Image': IMAGE, 'User': '10000:10000', 'Entrypoint': ['python'],
        'Cmd': ['/test_first_verify.py'], 'NetworkDisabled': True,
        'Env': ['TEST_FIRST_TEST_HASHES=' + json.dumps(hashes, sort_keys=True),
                'TEST_FIRST_RED_MANIFEST_SHA256=' + manifest_sha],
        'Labels': labels,
        'HostConfig': {'ReadonlyRootfs': True, 'NetworkMode': 'none',
                       'CapDrop': ['ALL'], 'SecurityOpt': ['no-new-privileges'],
                       'Memory': 67108864, 'NanoCpus': 500000000, 'PidsLimit': 16,
                       'Mounts': [{'Type': 'volume', 'Source': volume,
                                   'Target': '/delivery', 'ReadOnly': True},
                                  {'Type': 'volume', 'Source': red_volume,
                                   'Target': '/red', 'ReadOnly': True}]}})
    try:
        docker('POST', '/containers/' + name + '/start')
        deadline = time.time() + 20
        while time.time() < deadline:
            state = docker('GET', '/containers/' + name + '/json')['State']
            if not state['Running']:
                if state['ExitCode']:
                    raise ValueError('test changed after controller Red')
                result = json.loads(docker_stdout(name))
                if result != {'tests_unchanged': True, 'count': len(hashes)}:
                    raise ValueError('invalid test-first Green verification')
                return True
            time.sleep(.2)
        raise TimeoutError('test-first Green verification deadline')
    finally:
        info = docker('GET', '/containers/' + name + '/json')
        if info and info['Config'].get('Labels', {}).get('delivery-kit.source-task') == task_id:
            docker('DELETE', '/containers/' + info['Id'] + '?force=true')


def assign_review(payload):
    if not isinstance(payload, dict) or set(payload) != {'source_task_id', 'review_agent_id'}:
        raise ValueError('review assignment requires exact identities')
    source_id, reviewer_id = payload['source_task_id'], payload['review_agent_id']
    if any(str(uuid.UUID(value)) != value for value in (source_id, reviewer_id)):
        raise ValueError('invalid review identity')
    with LOCK, db() as con:
        snapshot = con.execute("SELECT volume FROM snapshots WHERE task_id=? AND status='complete'", (source_id,)).fetchone()
        author = con.execute('SELECT agent_id FROM native_bindings WHERE task_id=? ORDER BY rowid DESC LIMIT 1', (source_id,)).fetchone()
        settings = json.loads((STATE / 'native.json').read_text())
        if not snapshot or not author or author['agent_id'] == reviewer_id or settings['agents'].get(reviewer_id) != 'review':
            raise ValueError('independent review prerequisites not met')
        existing = con.execute('SELECT source_task_id,volume FROM review_assignments WHERE review_agent_id=?', (reviewer_id,)).fetchone()
        if existing:
            if existing['source_task_id'] == source_id and existing['volume'] == snapshot['volume']:
                return {'status': 'assigned', 'source_task_id': source_id, 'review_agent_id': reviewer_id}
            busy = con.execute("SELECT 1 FROM native_bindings n JOIN leases l USING(request_id) "
                               "WHERE n.agent_id=? AND l.status IN ('creating','running')",
                               (reviewer_id,)).fetchone()
            if busy:
                raise ValueError('prior review still active')
            con.execute('UPDATE review_assignments SET source_task_id=?,volume=? WHERE review_agent_id=?',
                        (source_id, snapshot['volume'], reviewer_id))
            return {'status': 'assigned', 'source_task_id': source_id, 'review_agent_id': reviewer_id}
        con.execute('INSERT INTO review_assignments VALUES (?,?,?)',
                    (reviewer_id, source_id, snapshot['volume']))
        return {'status': 'assigned', 'source_task_id': source_id, 'review_agent_id': reviewer_id}


def validation_job_name(kind, source_task_id):
    # Coordinator and reviewer may validate the same immutable source at once.
    # Each invocation owns its container and can clean up only that invocation.
    if kind not in ('suite','validate'):raise ValueError('invalid validation job kind')
    return PREFIX + '-' + kind + '-' + source_task_id + '-' + uuid.uuid4().hex[:12]


def run_portable_suite(volume, source_task_id, specification, *, suite_evidence=False):
    """Run only the operator-frozen argv/image; never accept an agent command."""
    from portable_contract import IMAGE as PINNED_IMAGE
    image = specification['test_image']
    command = specification['test_command']
    if (not isinstance(image, str) or not PINNED_IMAGE.fullmatch(image)
            or not isinstance(command, list) or not 1 <= len(command) <= 16
            or any(not isinstance(arg, str) or not arg for arg in command)):
        raise ValueError('invalid portable test specification')
    name = validation_job_name('suite',source_task_id)
    docker('POST', '/containers/create?name=' + name, {
        'Image': image, 'User': '10000:10000', 'Entrypoint': [command[0]],
        'Cmd': command[1:], 'WorkingDir': '/delivery', 'NetworkDisabled': True,
        'Env': ['PYTHONDONTWRITEBYTECODE=1'],
        'Labels': {'delivery-kit.owner': OWNER, 'delivery-kit.source-task': source_task_id,
                   'com.docker.compose.project': PREFIX},
        'HostConfig': {'ReadonlyRootfs': True, 'NetworkMode': 'none',
                       'CapDrop': ['ALL'], 'SecurityOpt': ['no-new-privileges'],
                       'Memory': 268435456, 'NanoCpus': 1000000000, 'PidsLimit': 96,
                       'Mounts': [{'Type': 'volume', 'Source': volume,
                                   'Target': '/delivery', 'ReadOnly': True}],
                       'Tmpfs': {'/tmp': 'rw,nosuid,nodev,size=32m,mode=1777'}}})
    try:
        docker('POST', '/containers/' + name + '/start')
        deadline = time.time() + 120
        while time.time() < deadline:
            info = docker('GET', '/containers/' + name + '/json')
            if info and not info['State']['Running']:
                if info['State']['ExitCode'] != 0:
                    try:
                        from suite_failure import evidence, FrozenSuiteFailure, failing_source_files
                    except ImportError:
                        from broker.suite_failure import evidence, FrozenSuiteFailure, failing_source_files
                    output = docker_stdout(name, include_stderr=True, limit=65536)
                    receipt = evidence(info['State']['ExitCode'], output, source_task_id, volume)
                    with db() as con:
                        paths = con.execute('SELECT DISTINCT e.path FROM issue_editables e '
                            'JOIN native_bindings n USING(issue_id) WHERE n.task_id=? '
                            'ORDER BY e.path', (source_task_id,)).fetchall()
                        receipt['diagnostic_read_files'] = [row[0].removeprefix('/workspace/')
                            for row in paths if row[0].startswith('/workspace/')]
                        receipt['diagnostic_read_files'] = sorted(set(receipt['diagnostic_read_files']) |
                            set(failing_source_files(receipt, specification['test_files'])))
                        con.execute('CREATE TABLE IF NOT EXISTS frozen_suite_failures('
                                    'task_id TEXT, output_sha256 TEXT, receipt TEXT, output TEXT, '
                                    'PRIMARY KEY(task_id,output_sha256))')
                        con.execute('INSERT OR IGNORE INTO frozen_suite_failures VALUES (?,?,?,?)',
                                    (source_task_id, receipt['output_sha256'],
                                     json.dumps(receipt, sort_keys=True), output))
                    raise FrozenSuiteFailure(receipt)
                output = docker_stdout(name, include_stderr=True)
                if (not re.search(specification['test_success_pattern'], output)
                        or unacceptable_output(output)):
                    raise ValueError('portable test success evidence missing')
                match = re.search(specification['test_count_pattern'], output)
                count = int(match.group(1)) if match else 0
                if count < specification['minimum_tests']:
                    raise ValueError('portable test count too low')
                if suite_evidence:
                    return {'tests': count, 'output': output[-50000:],
                            'output_sha256': hashlib.sha256(output.encode()).hexdigest(),
                            'test_image': image, 'test_command': command}
                return count
            time.sleep(0.2)
        raise TimeoutError('portable frozen suite deadline')
    finally:
        info = docker('GET', '/containers/' + name + '/json')
        if info and info['Config'].get('Labels', {}).get('delivery-kit.source-task') == source_task_id:
            docker('DELETE', '/containers/' + info['Id'] + '?force=true')


def validate_frozen_delivery(volume, source_task_id, required_tests=(), *, suite_evidence=False, review_request_id=None):
    required_tests = tuple(sorted(set(required_tests)))
    if len(required_tests) > 10 or any(not re.fullmatch(r'test_[A-Za-z0-9_]{1,100}', name)
                                    for name in required_tests):
        raise ValueError('invalid required test names')
    try:
        import u3_delivery_review
    except ImportError:
        from broker import u3_delivery_review
    coverage = u3_delivery_review.validate(handoff_context(), volume, source_task_id,
                                          suite_evidence=suite_evidence, review_request_id=review_request_id)
    if coverage is not None:
        if required_tests:
            raise ValueError('coverage-only review cannot satisfy feature-specific requirements')
        return coverage
    name = validation_job_name('validate',source_task_id)
    with db() as con:
        source = con.execute('SELECT issue_id FROM native_bindings WHERE task_id=? ORDER BY rowid DESC LIMIT 1',
                             (source_task_id,)).fetchone()
    if not source or not source['issue_id']:
        raise ValueError('source issue identity missing')
    base = handoff_runtime.task_base(handoff_context(), source['issue_id'], source_task_id)
    docker('POST', '/containers/create?name=' + name, {
        'Image': OFFLINE_IMAGE, 'User': '10000:10000', 'Entrypoint': ['python'],
        'Cmd': ['/snapshot_validate.py'], 'NetworkDisabled': True,
        'Env': ['REQUIRED_TESTS=' + ','.join(required_tests)],
        'Labels': {'delivery-kit.owner': OWNER, 'delivery-kit.source-task': source_task_id,
                   'com.docker.compose.project': PREFIX},
        'HostConfig': {'ReadonlyRootfs': True, 'NetworkMode': 'none',
                       'CapDrop': ['ALL'], 'SecurityOpt': ['no-new-privileges'],
                       'Memory': 67108864, 'NanoCpus': 500000000, 'PidsLimit': 16,
                       'Mounts': [{'Type': 'volume', 'Source': volume,
                                   'Target': '/delivery', 'ReadOnly': True},
                                  {'Type': 'volume', 'Source': base['volume'],
                                   'Target': '/base', 'ReadOnly': True}],
                       'Tmpfs': {'/tmp': 'rw,nosuid,nodev,size=8m,mode=1777'}}})
    try:
        docker('POST', '/containers/' + name + '/start')
        deadline = time.time() + 20
        while time.time() < deadline:
            info = docker('GET', '/containers/' + name + '/json')
            if info and not info['State']['Running']:
                if info['State']['ExitCode'] != 0:
                    try:
                        failure = json.loads(docker_stdout(name))
                    except (ValueError, RuntimeError):
                        raise ValueError('frozen delivery validation failed') from None
                    missing = failure.get('missing') if isinstance(failure, dict) else None
                    if (isinstance(failure, dict) and failure.get('error') == 'required_test_missing'
                            and isinstance(missing, list) and missing
                            and set(missing) <= set(required_tests)):
                        raise RequiredTestMissing(missing)
                    if (isinstance(failure, dict) and failure.get('error') == 'validation_failed'
                            and isinstance(failure.get('reason'), str) and len(failure['reason']) <= 300):
                        raise ValueError('artifact_validation: ' + failure['reason'])
                    raise ValueError('frozen delivery validation failed')
                result = json.loads(docker_stdout(name))
                if result.get('mode') == 'portable':
                    legacy_keys = {'mode', 'manifest_sha256', 'baseline_tests_intact',
                                        'test_image', 'test_command', 'test_success_pattern',
                                        'test_count_pattern', 'test_files', 'minimum_tests'}
                    checkpoint_keys = {'base_manifest_sha256','baseline_test_sha256','new_test_sha256'}
                    if (set(result) not in (legacy_keys,legacy_keys | checkpoint_keys)
                            or not re.fullmatch(r'[0-9a-f]{64}', result['manifest_sha256'])
                            or result['baseline_tests_intact'] is not True
                            or type(result['minimum_tests']) is not int
                            or not 1 <= result['minimum_tests'] <= 128):
                        raise ValueError('invalid portable structural receipt')
                    suite = run_portable_suite(volume, source_task_id, result,
                                               suite_evidence=True) if suite_evidence else None
                    tests = suite['tests'] if suite else run_portable_suite(volume, source_task_id, result)
                    return {'manifest_sha256': result['manifest_sha256'],
                            **({'checkpoint_evidence': {k:result[k] for k in checkpoint_keys}}
                               if checkpoint_keys <= set(result) else {}),
                            'tests': tests, 'baseline_tests_intact': True,
                            'portable': True, **({'suite': suite} if suite else {})}
                if (set(result) != {'manifest_sha256', 'tests', 'baseline_tests_intact'}
                        or len(result['manifest_sha256']) != 64 or not isinstance(result['tests'], int)
                        or result['tests'] < 3
                        or result['baseline_tests_intact'] is not True):
                    raise ValueError('invalid validator receipt')
                return result
            time.sleep(0.2)
        raise TimeoutError('frozen validation deadline')
    finally:
        info = docker('GET', '/containers/' + name + '/json')
        if info and info['Config'].get('Labels', {}).get('delivery-kit.source-task') == source_task_id:
            docker('DELETE', '/containers/' + info['Id'] + '?force=true')


def record_review(payload):
    if not isinstance(payload, dict) or set(payload) != {'review_task_id'}:
        raise ValueError('review requires exact task identity')
    review_task_id = payload['review_task_id']
    if str(uuid.UUID(review_task_id)) != review_task_id:
        raise ValueError('invalid review task')
    from native import task_record, task_messages
    with LOCK, db() as con:
        prior = con.execute('SELECT * FROM reviews WHERE review_task_id=?', (review_task_id,)).fetchone()
        row = con.execute('SELECT n.request_id,n.agent_id,g.mode,l.status FROM native_bindings n '
                          'JOIN grants g USING(request_id) JOIN leases l USING(request_id) '
                          'WHERE n.task_id=? ORDER BY g.attempt DESC LIMIT 1', (review_task_id,)).fetchone()
        if not row or row['mode'] != 'review' or row['status'] != 'closed':
            raise ValueError('review execution not closed')
        assignment = con.execute('SELECT * FROM review_assignments WHERE review_agent_id=?',
                                 (row['agent_id'],)).fetchone()
        if not assignment:
            raise ValueError('review snapshot assignment missing')
        bound = con.execute('SELECT source_task_id,volume FROM review_bindings WHERE request_id=?',
                            (row['request_id'],)).fetchone()
        if not bound or bound['source_task_id'] != assignment['source_task_id'] or bound['volume'] != assignment['volume']:
            raise ValueError('stale review binding')
        snapshot = con.execute("SELECT volume FROM snapshots WHERE task_id=? AND status='complete'",
                               (assignment['source_task_id'],)).fetchone()
        if not snapshot or snapshot['volume'] != assignment['volume']:
            raise ValueError('review snapshot changed')
        source_agent = con.execute('SELECT agent_id FROM native_bindings WHERE task_id=? '
                                   'ORDER BY rowid DESC LIMIT 1', (assignment['source_task_id'],)).fetchone()
        if not source_agent or source_agent['agent_id'] == row['agent_id']:
            raise ValueError('self-review forbidden')
        if prior:
            if (prior['source_task_id'] != assignment['source_task_id']
                    or prior['reviewer_agent_id'] != row['agent_id']):
                raise ValueError('stale review receipt')
            if prior['status'] == 'approved':
                con.execute("UPDATE review_incidents SET status='resolved' WHERE review_task_id IN "
                            "(SELECT n.task_id FROM native_bindings n JOIN review_bindings b "
                            "USING(request_id) WHERE b.source_task_id=?)",
                            (assignment['source_task_id'],))
            return dict(prior)
        settings = json.loads((STATE / 'native.json').read_text())
        task = task_record(settings, review_task_id, row['agent_id'])
        if task.get('status') != 'completed':
            raise ValueError('review task incomplete')
        messages = task_messages(settings, review_task_id)
        required_tests = [r['test_name'] for r in con.execute(
            'SELECT test_name FROM issue_requirements WHERE issue_id=? UNION '
            'SELECT test_name FROM change_requirements WHERE issue_id=?',
            (task['issue_id'], task['issue_id'])).fetchall()]
        try:
            validation = validate_frozen_delivery(assignment['volume'], assignment['source_task_id'],
                                                  required_tests)
        except RequiredTestMissing as missing:
            finding = 'add ' + ', '.join(missing.names) + ' while preserving all existing tests'
            con.execute('INSERT INTO reviews VALUES (?,?,?,?,?)',
                        (review_task_id, assignment['source_task_id'], row['agent_id'],
                         '', 'changes_requested'))
            con.execute('INSERT INTO review_findings VALUES (?,?)', (review_task_id, finding))
            return dict(con.execute('SELECT * FROM reviews WHERE review_task_id=?',
                                    (review_task_id,)).fetchone())
        decisions = review_decisions(messages)
        if len(set(decisions)) != 1 or not decisions:
            raise ValueError('review decision missing or conflicting')
        if decisions[0] == 'REQUEST_CHANGES':
            con.execute('INSERT INTO reviews VALUES (?,?,?,?,?)',
                        (review_task_id, assignment['source_task_id'], row['agent_id'],
                         '', 'changes_requested'))
            return dict(con.execute('SELECT * FROM reviews WHERE review_task_id=?',
                                    (review_task_id,)).fetchone())
        if not validation.get('portable') and not observed_passing_unittest(messages):
            raise ValueError('review approval or observed tests missing')
        try:
            import review_suite_rpc
        except ImportError:
            from broker import review_suite_rpc
        review_suite_rpc.require_approval_proof(con, row['request_id'],
            assignment['source_task_id'], validation['manifest_sha256'])
        try:import u3_delivery_review
        except ImportError:from broker import u3_delivery_review
        read_paths=u3_delivery_review.read_contract(handoff_context(),row['request_id'])
        if read_paths:
            try:from handoff_runtime import Effects
            except ImportError:from broker.handoff_runtime import Effects
            u3_delivery_review.require_complete_reads(Effects(handoff_context(),settings).read_evidence(task))
        con.execute('INSERT INTO reviews VALUES (?,?,?,?,?)',
                    (review_task_id, assignment['source_task_id'], row['agent_id'],
                     validation['manifest_sha256'], 'approved'))
        con.execute("UPDATE review_incidents SET status='resolved' WHERE review_task_id IN "
                    "(SELECT n.task_id FROM native_bindings n JOIN review_bindings b "
                    "USING(request_id) WHERE b.source_task_id=?)",
                    (assignment['source_task_id'],))
        return dict(con.execute('SELECT * FROM reviews WHERE review_task_id=?', (review_task_id,)).fetchone())


def review_decisions(messages):
    """Accept only an anchored, explicit final verdict, not incidental prose."""
    pattern = (r'^\s*(?:#{1,3}\s+)?(?:\*\*)?(?:Decision|Review verdict|Verdict):\s*'
               r'(?:\*\*)?(APPROVE|REQUEST_CHANGES)\b')
    return [match.group(1) for message in messages if message.get('type') == 'text'
            for match in re.finditer(pattern, message.get('content') or '', re.MULTILINE)]


def observed_passing_unittest(messages):
    """Require a real terminal call; tolerate Hermes truncating verbose tail."""
    test_commands = {m.get('call_id') for m in messages if m.get('type') == 'tool_use'
                     and m.get('tool') == 'terminal' and 'unittest' in str(m.get('input', ''))}
    for result in messages:
        if result.get('type') != 'tool_result' or result.get('call_id') not in test_commands:
            continue
        output = result.get('output') or ''
        if re.search(r'Ran (?:[3-9]|\d{2,}) tests? in ', output) and '\nOK' in output:
            return True
        if ('**exit_code:** 0' in output
                and len(re.findall(r'test_\w+[^\n]*\.\.\. ok', output)) >= 3
                and not re.search(r'\b(?:FAILED|ERROR|skipped|expected failure)\b', output, re.IGNORECASE)):
            return True
    return False


def reconcile_review_outcomes():
    """Record completed review outcomes; never treat text-only completion as approval."""
    with LOCK, db() as con:
        pending = con.execute("SELECT DISTINCT n.task_id FROM native_bindings n "
                              "JOIN grants g USING(request_id) JOIN leases l USING(request_id) "
                              "JOIN review_bindings b USING(request_id) "
                              "WHERE g.mode='review' AND l.status='closed' "
                              "AND n.task_id NOT IN (SELECT review_task_id FROM reviews) "
                              "AND n.task_id NOT IN (SELECT review_task_id FROM review_incidents)").fetchall()
    for row in pending:
        task_id = row['task_id']
        try:
            record_review({'review_task_id': task_id})
        except ValueError as exc:
            # A native task may still be settling after the ACP lease closes.
            if str(exc) == 'review task incomplete':
                continue
            infrastructure_limit = False
            try:
                from native import task_messages
                settings = json.loads((STATE / 'native.json').read_text())
                infrastructure_limit = any('evaluation_model_call_limit' in
                                           ((m.get('content') or '') + (m.get('output') or ''))
                                           for m in task_messages(settings, task_id))
            except Exception:
                pass
            with LOCK, db() as con:
                approved = con.execute('SELECT 1 FROM review_bindings b JOIN reviews r '
                                       'ON r.source_task_id=b.source_task_id WHERE b.request_id IN '
                                       '(SELECT request_id FROM native_bindings WHERE task_id=?) LIMIT 1',
                                       (task_id,)).fetchone()
                con.execute('INSERT OR IGNORE INTO review_incidents VALUES (?,?,?,?)',
                            (task_id, str(exc), 'resolved' if approved else
                             'infrastructure_model_limit' if infrastructure_limit else 'open',
                             time.time()))
        except Exception:
            # Connectivity/validator infrastructure failure is not a review verdict.
            continue
        else:
            with LOCK, db() as con:
                source = con.execute('SELECT source_task_id FROM reviews WHERE review_task_id=?',
                                     (task_id,)).fetchone()
                if source:
                    con.execute("UPDATE review_incidents SET status='resolved' WHERE review_task_id IN "
                                "(SELECT n.task_id FROM native_bindings n JOIN review_bindings b "
                                "USING(request_id) WHERE b.source_task_id=?)",
                                (source['source_task_id'],))


def reconcile_review_retries():
    """Convert an incident to one native wakeup; never dispatch a worker here."""
    from native import task_record, ensure_review_retry_wakeup
    settings = json.loads((STATE / 'native.json').read_text())
    with LOCK, db() as con:
        incidents = con.execute("SELECT i.review_task_id,n.agent_id,b.source_task_id "
                                "FROM review_incidents i JOIN native_bindings n ON n.task_id=i.review_task_id "
                                "JOIN review_bindings b USING(request_id) WHERE i.status='open'").fetchall()
    for incident in incidents:
        review_task_id = incident['review_task_id']
        source_id = incident['source_task_id']
        if managed_delivery_task(source_id):
            continue
        reviewer_id = incident['agent_id']
        with LOCK, db() as con:
            approved = con.execute("SELECT 1 FROM reviews WHERE source_task_id=? AND status='approved' LIMIT 1",
                                   (source_id,)).fetchone()
            count = con.execute('SELECT count(DISTINCT n.task_id) FROM review_bindings b '
                                'JOIN native_bindings n USING(request_id) WHERE b.source_task_id=?',
                                (source_id,)).fetchone()[0]
            if approved:
                con.execute("UPDATE review_incidents SET status='resolved' WHERE review_task_id=?",
                            (review_task_id,))
                continue
            if count >= 2:
                con.execute("UPDATE review_incidents SET status='escalation_required' WHERE review_task_id=?",
                            (review_task_id,))
                continue
        try:
            task = task_record(settings, review_task_id, reviewer_id)
            if task.get('status') != 'completed' or not task.get('issue_id'):
                continue
            wakeup_id = ensure_review_retry_wakeup(settings, task['issue_id'], review_task_id,
                                                    reviewer_id)
        except Exception:
            with LOCK, db() as con:
                attempts = con.execute('SELECT attempts FROM review_retry_attempts WHERE review_task_id=?',
                                       (review_task_id,)).fetchone()
                next_attempt = (attempts['attempts'] if attempts else 0) + 1
                con.execute('INSERT OR REPLACE INTO review_retry_attempts VALUES (?,?)',
                            (review_task_id, next_attempt))
                if next_attempt >= 2:
                    con.execute("UPDATE review_incidents SET status='escalation_required' WHERE review_task_id=?",
                                (review_task_id,))
            continue
        with LOCK, db() as con:
            con.execute("UPDATE review_incidents SET status='retry_queued' WHERE review_task_id=?",
                        (review_task_id,))
            con.execute('INSERT OR REPLACE INTO review_retry_wakeups VALUES (?,?)',
                        (review_task_id, wakeup_id))


def reconcile_change_requests():
    """Ask the original author to correct a rejected snapshot via native wakeups."""
    from native import task_record, task_messages, ensure_change_request_wakeups
    settings = json.loads((STATE / 'native.json').read_text())
    with LOCK, db() as con:
        pending = con.execute("SELECT r.review_task_id,r.source_task_id,r.reviewer_agent_id,"
                              "n.agent_id AS implementer_id FROM reviews r "
                              "JOIN native_bindings n ON n.task_id=r.source_task_id "
                              "WHERE r.status='changes_requested' AND r.review_task_id NOT IN "
                              "(SELECT review_task_id FROM change_handoffs) AND r.review_task_id NOT IN "
                              "(SELECT review_task_id FROM change_handoff_failures WHERE attempts>=2) "
                              "GROUP BY r.review_task_id").fetchall()
    for row in pending:
        if managed_delivery_task(row['source_task_id']):
            continue
        with LOCK, db() as con:
            scope = con.execute('SELECT scope FROM native_bindings WHERE task_id=? LIMIT 1',
                                (row['source_task_id'],)).fetchone()
            repeated = con.execute("SELECT count(DISTINCT r.review_task_id) FROM reviews r "
                                   "JOIN native_bindings n ON n.task_id=r.source_task_id "
                                   "WHERE r.status='changes_requested' AND n.scope=?",
                                   (scope['scope'] if scope else '',)).fetchone()[0]
            if repeated > 2:
                con.execute('INSERT OR REPLACE INTO change_handoff_failures VALUES (?,?,?)',
                            (row['review_task_id'], 2, 'repeated_change_requests_escalate'))
                continue
        try:
            task = task_record(settings, row['review_task_id'], row['reviewer_agent_id'])
            if task.get('status') != 'completed' or not task.get('issue_id'):
                continue
            with db() as con:
                controlled = con.execute('SELECT finding FROM review_findings WHERE review_task_id=?',
                                         (row['review_task_id'],)).fetchone()
            if controlled:
                finding = controlled['finding']
            else:
                findings = [m.get('content') or '' for m in task_messages(settings, row['review_task_id'])
                            if m.get('type') == 'text' and 'Decision: REQUEST_CHANGES' in (m.get('content') or '')]
                if not findings:
                    continue
                finding = change_request_reason(findings[-1])
            required_tests = set(re.findall(r'\btest_[A-Za-z0-9_]{1,100}\b', finding))
            with LOCK, db() as con:
                for test_name in required_tests:
                    con.execute('INSERT OR IGNORE INTO change_requirements VALUES (?,?,?)',
                                (task['issue_id'], row['review_task_id'], test_name))
            wakeups = ensure_change_request_wakeups(settings, task['issue_id'],
                row['review_task_id'], row['implementer_id'], row['reviewer_agent_id'], finding)
        except Exception as exc:
            # Exact native wakeup lookup makes the next bounded attempt idempotent.
            with LOCK, db() as con:
                old = con.execute('SELECT attempts FROM change_handoff_failures WHERE review_task_id=?',
                                  (row['review_task_id'],)).fetchone()
                con.execute('INSERT OR REPLACE INTO change_handoff_failures VALUES (?,?,?)',
                            (row['review_task_id'], (old['attempts'] if old else 0) + 1,
                             type(exc).__name__))
            continue
        with LOCK, db() as con:
            con.execute('INSERT OR IGNORE INTO change_handoffs VALUES (?,?,?)',
                        (row['review_task_id'], wakeups['reviewer_wakeup_id'],
                         wakeups['implementer_wakeup_id']))
            con.execute('DELETE FROM change_handoff_failures WHERE review_task_id=?',
                        (row['review_task_id'],))


def change_request_reason(content):
    decision = re.search(r'Decision:\s*REQUEST_CHANGES\s*[;.\-]?\s*Reason:\s*([^\r\n]+)',
                         content)
    if decision and decision.group(1).strip():
        return decision.group(1).strip()
    # Preserve liveness when an otherwise valid reviewer uses a dash instead of
    # the requested Reason label. Still require one explicit decision line.
    fallback = re.search(r'^Decision:\s*REQUEST_CHANGES\s*[—–-]\s*([^\r\n]+)',
                         content, re.MULTILINE)
    if fallback and fallback.group(1).strip():
        return fallback.group(1).strip()
    raise ValueError('change request lacks structured reason')


def execute_grant(token, payload, streaming=False):
    if payload != {}:
        raise ValueError('execution parameters are controller-owned')
    with LOCK, db() as con:
        row = con.execute('SELECT * FROM grants WHERE digest=?',
                          (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
        if not row or row['deadline'] < time.time():
            raise ValueError('invalid or expired capability')
        if row['mode'] == 'implementation' and not native_scope(row['request_id']):
            raise ValueError('implementation requires native binding')
        latest = con.execute('SELECT max(attempt) FROM grants WHERE task_id=?', (row['task_id'],)).fetchone()[0]
        if row['attempt'] != latest:
            raise ValueError('stale attempt')
        if row['used']:
            raise ValueError('capability already consumed')
        scope = native_scope(row['request_id'])
        if scope:
            from native import task_binding
            binding = con.execute('SELECT * FROM native_bindings WHERE request_id=?', (row['request_id'],)).fetchone()
            current = task_binding(json.loads((STATE / 'native.json').read_text()), binding['task_id'], binding['agent_id'])
            if current['scope'] != scope:
                raise ValueError('native scope changed before launch')
        if scope and con.execute("SELECT 1 FROM native_bindings n JOIN leases l USING(request_id) WHERE n.scope=? AND l.status IN ('creating','running')", (scope,)).fetchone():
            raise ValueError('persistent session scope busy')
        con.execute('UPDATE grants SET used=1 WHERE digest=?', (row['digest'],))
        con.commit()  # fail closed if interrupted before launch; never replay the old grant
        # Implementation is limited to a task-scoped workspace volume.
        result = submit({'request_id': row['request_id'], 'scenario': 'acp-session' if streaming else 'acp'}, trusted_acp=True)
        if result['status']!='running':
            raise ValueError('worker startup requires observation before transport')
        if streaming:
            from acp_transport import Transport
            try:
                with db() as lookup:
                    binding = lookup.execute('SELECT scope,issue_id,task_id FROM native_bindings WHERE request_id=?', (row['request_id'],)).fetchone()
                    editables = [r[0] for r in lookup.execute(
                        'SELECT path FROM issue_editables WHERE issue_id=?',
                        (binding['issue_id'],))] if binding else []
                    test_commands = [r[0] for r in lookup.execute(
                        'SELECT command FROM issue_test_commands WHERE issue_id=?',
                        (binding['issue_id'],))] if binding else []
                    phase = implementation_phase(binding['issue_id']) if binding else None
                    route_row = lookup.execute('SELECT config FROM delivery_routes WHERE issue_id=?',
                                               (binding['issue_id'],)).fetchone() if binding else None
                    editables = phase_editables(editables,
                        json.loads(route_row[0]) if route_row else None, phase, row['mode'])
                if row['mode'] == 'implementation' and route_row:
                    lock_workspace(binding['issue_id'], binding['scope'],
                                   PREFIX + '-work-' + hashlib.sha256(binding['scope'].encode()).hexdigest()[:32],
                                   editables)
                if row['mode'] == 'implementation' and not editables:
                    editables = ['/workspace/calc.py', '/workspace/test_calc.py']
                suite_capability = None
                if row['mode'] == 'review' and binding:
                    import review_suite_rpc
                    suite_capability = review_suite_rpc.issue(handoff_context(), row['request_id'])
                SESSIONS[row['request_id']] = Transport(
                    docker, result['name'], persistent=bool(binding), mode=row['mode'],
                    editable_paths=editables, test_commands=test_commands,
                    review_suite_capability=suite_capability)
            except Exception as error:
                remove_owned(result['name'], row['request_id'])
                with db() as failed:
                    failed.execute("UPDATE leases SET status='failed' WHERE request_id=?", (row['request_id'],))
                    failed.execute('INSERT INTO broker_errors VALUES (?,?,?,?)',
                                   (row['request_id'], 'transport_start',
                                    'bootstrap:' + failure_category(error), time.time()))
                raise
            if scope:
                from session_resume import prior_session
                with db() as lookup:
                    prior = prior_session(lookup, scope, binding['task_id'])
                if prior:
                    result['resume_session_id'] = prior
        return result


def assert_review_task_running(row):
    from native import task_binding
    current = task_binding(json.loads((STATE / 'native.json').read_text()),
                           row['task_id'], row['agent_id'])
    if current['scope'] != row['scope']:
        raise ValueError('review suite native scope drift')


def session_operation(token, payload, close=False, on_notification=None):
    with LOCK, db() as con:
        grant = con.execute('SELECT * FROM grants WHERE digest=?',
                            (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
        if not grant or grant['deadline'] < time.time():
            raise ValueError('invalid session capability')
        lease = con.execute('SELECT * FROM leases WHERE request_id=?', (grant['request_id'],)).fetchone()
        if close and payload != {}:
            raise ValueError('close takes no parameters')
        if close and lease and lease['status'] == 'closed':
            return {'status': 'closed'}
        if not lease or lease['status'] not in (('running','closing') if close else ('running',)) or lease['deadline'] <= time.time():
            raise ValueError('execution is no longer active')
        binding = con.execute('SELECT * FROM native_bindings WHERE request_id=?', (grant['request_id'],)).fetchone()
        if binding and not close:
            from native import task_binding
            current = task_binding(json.loads((STATE / 'native.json').read_text()), binding['task_id'], binding['agent_id'])
            if current['scope'] != binding['scope']:
                raise ValueError('native scope changed')
        session = SESSIONS.get(grant['request_id'])
        if session is None and not (close and lease['status'] == 'closing'):
            raise ValueError('session absent; cannot silently recreate after restart')
        if close:
            con.execute("UPDATE leases SET status='closing' WHERE request_id=? AND status='running'",
                        (grant['request_id'],))
            con.commit()  # write-ahead intent MUST survive removal or reply failure
            remove_owned(lease['name'], grant['request_id'])
            con.execute("UPDATE leases SET status='closed' WHERE request_id=?", (grant['request_id'],))
            return {'status': 'closed'}
        if set(payload) != {'frame'}:
            raise ValueError('frame required')
        frame = payload['frame']
        if frame.get('method') in ('session/resume', 'session/set_model', 'session/prompt'):
            sid = frame.get('params', {}).get('sessionId')
            if not binding or not con.execute('SELECT 1 FROM acp_sessions WHERE scope=? AND session_id=?', (binding['scope'], sid)).fetchone():
                raise ValueError('session does not belong to this scope')
    if binding and frame.get('method') == 'session/prompt':
        from native import issue_record
        settings = json.loads((STATE / 'native.json').read_text())
        issue = issue_record(settings, binding['issue_id'])
        correction = verified_correction(current, binding['issue_id']) if grant['mode'] == 'implementation' else None
        frame = native_task_prompt(frame, grant['mode'], issue, current, correction)
    result = session.exchange(frame, on_notification=on_notification) if on_notification else session.exchange(frame)
    with LOCK, db() as con:
        session_id = result.get('result', {}).get('sessionId') or frame.get('params', {}).get('sessionId')
        con.execute('INSERT INTO acp_events VALUES (?,?,?,?)', (grant['request_id'], frame['method'], session_id, int('result' in result and 'error' not in result)))
        if frame['method'] == 'session/prompt':
            import read_stream_receipts
            read_stream_receipts.store(con,binding,result.get('_broker_notifications',[]),grant['mode'])
            con.execute('INSERT OR REPLACE INTO tool_events VALUES (?,?,?)',
                        (grant['request_id'], str(frame['id']),
                         tool_call_receipts(result.get('_broker_notifications', []))))
    if binding and frame.get('method') == 'session/new' and result.get('result', {}).get('sessionId'):
        with LOCK, db() as con:
            con.execute('INSERT OR IGNORE INTO acp_sessions VALUES (?,?)', (binding['scope'], result['result']['sessionId']))
    return result


def managed_delivery_task(task_id):
    try:
        import u3_delivery_review
    except ImportError:
        from broker import u3_delivery_review
    if u3_delivery_review.manages_source(handoff_context(), task_id):
        return True  # One controller owns retries/change escalation for this coverage snapshot.
    with db() as con:
        if not con.execute("SELECT 1 FROM sqlite_master WHERE name='delivery_routes'").fetchone():
            return False
        return bool(con.execute('SELECT 1 FROM native_bindings n JOIN delivery_routes r USING(issue_id) '
                                'WHERE n.task_id=? LIMIT 1', (task_id,)).fetchone())


def verified_correction(task, issue_id):
    """Bind a reviewer finding to the exact controller-registered wakeup."""
    wakeup_id = task.get('wakeup_id')
    if not wakeup_id:
        return None
    with db() as con:
        if con.execute("SELECT 1 FROM sqlite_master WHERE name='delivery_handoffs'").fetchone():
            for row in con.execute('SELECT data FROM delivery_handoffs WHERE issue_id=?', (issue_id,)):
                item = json.loads(row[0])
                if (item.get('dispatch_stage') == 'correct_author'
                        and item.get('target') == task.get('agent_id')
                        and (item.get('wakeup_id') == wakeup_id
                             or ('DELIVERY_HANDOFF ' + item.get('dispatch_marker', '!')) in (task.get('handoff_note') or ''))):
                    return {'review_task_id': item['trigger_task'], 'finding': item['finding'][:600]}
        rows = con.execute(
            'SELECT h.review_task_id,f.finding FROM change_handoffs h '
            'JOIN review_findings f ON f.review_task_id=h.review_task_id '
            'JOIN reviews r ON r.review_task_id=h.review_task_id '
            'JOIN native_bindings n ON n.task_id=r.source_task_id '
            'WHERE h.implementer_wakeup_id=? AND n.issue_id=?',
            (wakeup_id, issue_id)).fetchall()
    if len(rows) > 1:
        raise ValueError('ambiguous verified change request')
    return dict(rows[0]) if rows else None


def has_verified_revision_brief(issue_id):
    """Longer child context requires controller lineage, never an agent claim."""
    if not issue_id:
        return False
    with db() as con:
        if not con.execute("SELECT 1 FROM sqlite_master WHERE name='test_revision_trials'").fetchone():
            return False
        row = con.execute('SELECT parent_issue,config FROM test_revision_trials WHERE issue_id=?',
                          (issue_id,)).fetchone()
    if not row or not row['parent_issue']:
        return False
    config = json.loads(row['config'])
    if config.get('parent_issue') != row['parent_issue']:
        raise ValueError('revision brief lineage mismatch')
    try:
        import test_revision_review
    except ImportError:
        from broker import test_revision_review
    # Reuse the authoritative same-base, same-author, same-contract and frozen
    # artifact identity checks. A description/wakeup cannot grant this exception.
    return test_revision_review.seed_source(handoff_context(), issue_id) is not None


def test_artifact_phase_context(issue_id, author):
    """Opt-in markers sourced only from registered controller paths."""
    if os.environ.get('BROKER_TEST_ARTIFACT_GATE') != '1':
        return ''
    with db() as con:
        row = con.execute('SELECT config FROM delivery_routes WHERE issue_id=?', (issue_id,)).fetchone()
        route = json.loads(row[0]) if row else {}
        try:import harness_repair_task
        except ImportError:from broker import harness_repair_task
        maintenance = harness_repair_task.registered_author(con,issue_id,author)
        if ((route.get('enabled') is not True and not maintenance) or route.get('test_first') is not True
                or route.get('author') != author or len(route.get('test_first_files', [])) != 1):
            raise ValueError('artifact phase requires exact registered single-test author')
        target = '/workspace/' + route['test_first_files'][0]
        paths = [r[0] for r in con.execute('SELECT path FROM issue_editables WHERE issue_id=?', (issue_id,))]
    if target not in paths:
        raise ValueError('artifact target is not an existing editable grant')
    sources = sorted(set(paths) - {target})
    if not 1 <= len(sources) <= 4:
        raise ValueError('artifact phase requires bounded registered product sources')
    from portable_contract import safe_path
    for path in [target, *sources]:
        if not path.startswith('/workspace/'):
            raise ValueError('artifact phase path outside workspace')
        safe_path(path.removeprefix('/workspace/'))
    return ('\nDELIVERY_TEST_ARTIFACT_V1:' + target + '\n'
            + ''.join('DELIVERY_TEST_SOURCE_V1:' + path + '\n' for path in sources)
            + 'DELIVERY_DETERMINISTIC_READ_V1\n')


def compact_diagnosis_note(issue,task,note):
    """Only an active controller-registered diagnosis can omit ambient backlog."""
    if not re.search(r'^DELIVERY_UNCHANGED_CORRECTION_DIAGNOSIS_V1$',note,re.M):return None
    with db() as con:
        rows=con.execute('SELECT stage,owner,data FROM delivery_handoffs WHERE issue_id=?',
                         (issue['id'],)).fetchall()
    for row in rows:
        data=json.loads(row['data'])
        marker=data.get('dispatch_marker')
        if (row['stage'] in ('dispatch_intent','awaiting_acceptance','accepted')
                and row['owner']==task.get('agent_id') and data.get('target')==row['owner']
                and data.get('dispatch_stage')=='diagnose_cto'
                and data.get('evidence',{}).get('correction_diagnosis',{}).get('category')=='unchanged_rejected_delivery'
                and isinstance(marker,str) and len(marker)==64
                and 'DELIVERY_HANDOFF '+marker in note
                and (not data.get('wakeup_id') or data['wakeup_id']==task.get('wakeup_id'))
                and data.get('instruction') and data['instruction'] in note):
            return data['instruction']
    raise ValueError('compact diagnosis requires active registered owner and handoff')


def compact_review_note(issue, task, note):
    """Remove native event wrapping only for an exact active frozen review.

    The controller instruction (including the TDD receipt) remains byte-identical.
    Caller text cannot confer a review identity or substitute delivery evidence.
    """
    if not isinstance(note, str) or len(note) <= 4000:
        return note
    task_id = task.get('task_id') or task.get('id')
    if not isinstance(task_id, str) or not task_id:
        raise ValueError('native review execution identity required')
    with db() as con:
        rows = con.execute('SELECT source_task,stage,owner,data FROM delivery_handoffs '
                           'WHERE issue_id=?', (issue['id'],)).fetchall()
        for row in rows:
            data = json.loads(row['data'])
            marker, instruction = data.get('dispatch_marker'), data.get('instruction')
            snapshot = con.execute('SELECT status FROM snapshots WHERE task_id=?',
                                   (row['source_task'],)).fetchone()
            evidence = data.get('evidence') or {}
            if (row['stage'] in ('dispatch_intent', 'awaiting_acceptance', 'accepted')
                    and row['owner'] == task.get('agent_id') == data.get('target')
                    and data.get('reviewer') == row['owner']
                    and data.get('author') != row['owner']
                    and data.get('dispatch_stage') == 'ready_review'
                    and data.get('wakeup_id') == task.get('wakeup_id')
                    and bool(data.get('wakeup_id'))
                    and isinstance(marker, str) and re.fullmatch('[a-f0-9]{64}', marker)
                    and isinstance(instruction, str) and instruction
                    and 'DELIVERY_HANDOFF ' + marker + '\n' + instruction in note
                    and snapshot and snapshot['status'] == 'complete'
                    and evidence.get('baseline_tests_intact') is True
                    and re.fullmatch('[a-f0-9]{64}', evidence.get('manifest_sha256', ''))
                    and evidence.get('tdd', {}).get('green', {}).get('executed_by_controller') is True):
                effective = 'DELIVERY_HANDOFF ' + marker + '\n' + instruction
                if len(effective) > 4000:
                    raise ValueError('registered review instruction exceeds bound')
                proof = dict(operation='registered_review_presentation_v1', issue_id=issue['id'],
                    source_task=row['source_task'], wakeup_id=task['wakeup_id'],
                    manifest_sha256=evidence['manifest_sha256'], approval=False,
                    original_sha256=hashlib.sha256(note.encode()).hexdigest(),
                    effective_sha256=hashlib.sha256(effective.encode()).hexdigest(),
                    original_characters=len(note), effective_characters=len(effective))
                con.execute('CREATE TABLE IF NOT EXISTS review_context_presentations('
                            'task_id TEXT PRIMARY KEY,receipt TEXT)')
                old = con.execute('SELECT receipt FROM review_context_presentations WHERE task_id=?',
                                  (task_id,)).fetchone()
                if old and json.loads(old[0]) != proof:
                    raise ValueError('review presentation drift')
                con.execute('INSERT OR IGNORE INTO review_context_presentations VALUES (?,?)',
                            (task_id, json.dumps(proof, sort_keys=True)))
                return effective
    raise ValueError('oversized review requires exact active frozen handoff')


def native_task_prompt(frame, mode, issue, task, correction=None):
    """Controller-supplied task context; workers never need Multica network."""
    if mode not in ('implementation', 'review', 'planning'):
        raise ValueError('invalid native mode')
    if frame.get('method') != 'session/prompt':
        raise ValueError('prompt frame required')
    if mode=='implementation' and 'DELIVERY_ADDITIVE_CONTROL_V1' in (task.get('handoff_note') or ''):
        try:import u3_controls_execution
        except ImportError:from broker import u3_controls_execution
        additive=u3_controls_execution.grant(handoff_context(),issue.get('id'),task)
        if additive:
            return {**frame,'params':{**frame['params'],'prompt':[{'type':'text','text':additive['note']}]}}
    title, description = issue.get('title'), issue.get('description')
    from execution_context import registered as registered_context, reference as context_reference
    with db() as con:
        capsule = registered_context(con, mode, issue.get('id'), task.get('agent_id'), description)
    if capsule is not None:
        description = capsule['description']
        receipt_task_id = task.get('task_id') or task.get('id')
        if not isinstance(receipt_task_id, str) or not receipt_task_id:
            raise ValueError('registered context execution identity required')
        proof = dict(issue_id=issue.get('id'), task_id=receipt_task_id,
                     agent_id=task.get('agent_id'), mode=mode,
                     context_sha256=capsule['sha256'], delivery_approval=False)
        with db() as con:
            con.execute('CREATE TABLE IF NOT EXISTS execution_context_presentations('
                        'task_id TEXT PRIMARY KEY, receipt TEXT)')
            old = con.execute('SELECT receipt FROM execution_context_presentations WHERE task_id=?',
                              (receipt_task_id,)).fetchone()
            if old and json.loads(old[0]) != proof:
                raise ValueError('registered execution context presentation drift')
            con.execute('INSERT OR IGNORE INTO execution_context_presentations VALUES (?,?)',
                        (receipt_task_id, json.dumps(proof, sort_keys=True)))
    current=None
    if mode=='implementation' and re.search(r'(?:^|\n)DELIVERY_DRIVER_CHECKPOINT_V3(?:\n|$)',task.get('handoff_note') or ''):
        try:import harness_repair_task
        except ImportError:from broker import harness_repair_task
        with db() as con:current=harness_repair_task.current_maintenance_context(con,issue,task)
        title,description=current['title'],current['description']
    if mode=='planning' and re.search(r'(?:^|\n)DELIVERY_CURRENT_HARNESS_DIAGNOSIS_V1(?:\n|$)',task.get('handoff_note') or ''):
        try:import harness_repair_task
        except ImportError:from broker import harness_repair_task
        with db() as con:current=harness_repair_task.current_diagnosis_context(con,issue,task)
        title,description=current['title'],current['description']
    if mode != 'planning' and capsule is None:
        from generated_context import compact as compact_generated_context
        description, context_presentation = compact_generated_context(description)
        if context_presentation:
            with db() as con:
                con.execute('CREATE TABLE IF NOT EXISTS generated_context_presentations('
                            'task_id TEXT PRIMARY KEY, receipt TEXT)')
                proof = {**context_presentation, 'issue_id': issue.get('id')}
                receipt_task_id = task.get('task_id') or task.get('id')
                if not isinstance(receipt_task_id, str) or not receipt_task_id:
                    raise ValueError('native generated context execution identity required')
                old = con.execute('SELECT receipt FROM generated_context_presentations WHERE task_id=?',
                                  (receipt_task_id,)).fetchone()
                if old and json.loads(old[0]) != proof:
                    raise ValueError('generated context presentation drift')
                con.execute('INSERT OR IGNORE INTO generated_context_presentations VALUES (?,?)',
                            (receipt_task_id, json.dumps(proof, sort_keys=True)))
    description_limit = 12000 if capsule is not None else (8000 if mode == 'planning' else 4000)
    if (mode != 'planning' and isinstance(description, str)
            and 4000 < len(description) <= 8000
            and has_verified_revision_brief(issue.get('id'))):
        description_limit = 8000
    if not isinstance(title, str) or not isinstance(description, str) or \
            not 0 < len(title) <= 200 or not 0 < len(description) <= description_limit:
        raise ValueError('bounded issue brief required')
    note = task.get('handoff_note') or ''
    if mode == 'review':
        note = compact_review_note(issue, task, note)
        if capsule is not None:
            ref = context_reference(capsule, 'review')
            if note.count(ref) != 1:
                raise ValueError('registered review context reference required')
            note = note.replace(ref, capsule['review_instruction'])
    # Multica wraps the bounded 4000-character instruction with event context.
    if not isinstance(note, str) or len(note) > (16000 if capsule is not None else (8000 if mode == 'planning' else 4000)):
        raise ValueError('invalid handoff note')
    if current is not None:
        note=current['handoff_note']
        if not isinstance(note,str) or not 0<len(note)<=4000:raise ValueError('bounded current maintenance handoff required')
    if mode=='planning' and 'DELIVERY_BOUND_FAILURE_CONTEXT_V1:' in note:
        import bound_failure_context
        with db() as con:
            note=bound_failure_context.expand(note,issue['id'],task,
                lambda source:con.execute('SELECT issue_id,data FROM delivery_handoffs WHERE source_task=?',(source,)).fetchone())
    if mode=='planning':
        compact=compact_diagnosis_note(issue,task,note)
        if compact is not None:
            if correction is not None:raise ValueError('diagnosis cannot receive implementation correction')
            return {**frame,'params':{**frame['params'],
                'prompt':[{'type':'text','text':compact}]}}
    instruction = (
        'Implement in /workspace only. Follow Red-Green-Refactor, preserve all '
        'existing tests, run the entire suite and report exact commands/results.'
        if mode == 'implementation' else
        'Review the immutable /delivery only. Do not edit files. Run the full '
        'suite, verify pre-existing tests and record APPROVE or REQUEST_CHANGES '
        'with a concrete reason.'
        if mode == 'review' else
        'Plan from the verified issue brief only. You have no repository, shell, '
        'file, Docker, GitHub or administrative tools. Produce a concrete, '
        'bounded proposal with assumptions and decisions for your assigned role. '
        'Do not claim to have created cards, edited files or executed tests.'
    )
    qa_config = None
    if mode == 'planning' and 'QA_DIAGNOSIS_V1' in description:
        try:
            import qa_artifacts
        except ImportError:
            from broker import qa_artifacts
        qa_config = qa_artifacts.config_for(handoff_context(), issue['id'], task.get('agent_id'))
        if not qa_config:
            raise ValueError('QA planning artifact registration required')
        note += '\n' + ''.join('DELIVERY_REVIEW_READ_PATH:' + p + '\n' for p in qa_artifacts.read_paths(qa_config))
        note += '\nDELIVERY_STRUCTURED_DECISION_V1:qa\n'
        note += ('\nRead evidence with read_file offset=1, limit=60, then consecutive '
                 '60-line pages until EOF. A truncated output is NOT proof of reading; '
                 'request bounded pages. Read the entire receipt and scenario and at least '
                 'one product file before deciding. Use repository-relative paths in JSON '
                 '(app/static/app.js, never /evidence/candidate/...). root_cause max1000 '
                 'characters; acceptance at most5 strings, each max300 characters. '
                 'For blocked use empty code files, empty new_test_file and empty acceptance. '
                 'Distinguish observed facts from hypotheses; never invent an executed '
                 'experiment or timing race not supported by the artifact evidence.\n')
    if mode == 'planning' and ('/evidence/candidate' in note or qa_config):
        instruction = ('Analyze only the controller-mounted read-only /evidence/candidate '
                       'and /evidence/previous using file-read tools. No shell, writes, '
                       'Docker, GitHub or administrative operations. Return the exact '
                       'decision format requested in the verified handoff note. Do not '
                       'claim to have changed files or executed tests.')
        if not qa_config and 'DELIVERY_STRUCTURED_DECISION_V1:test_review:' not in note:
            instruction += '\nDELIVERY_STRUCTURED_DECISION_V1:technical\n'
        # The fixed read schema already selects the exact mounted path/page.
        # Dispatch that request directly; actual tool results still gate the
        # model's decision. Never synthesize source, tests or an approval.
        instruction += '\nDELIVERY_DETERMINISTIC_READ_V1\n'
    if mode == 'implementation':
        phase = implementation_phase(issue.get('id'))
        if phase == 'await_test_review':
            raise ValueError('independent new-test review required before implementation')
        if phase == 'tests_only':
            instruction = ('TEST-FIRST PHASE. Write only the declared new test files. '
                           'Do not create or modify application code, assets, baseline files '
                           'or existing tests. Do not reconstruct Red in a temporary tree. '
                           'Each file is limited to 32768 UTF-8 bytes; keep tests concise '
                           'and reuse faithful harness patterns rather than duplicating them. '
                           'Finish after tests express the acceptance criteria; the controller '
                           'will freeze the unchanged base plus your tests and execute Red '
                           'itself before any implementation handoff.')
            instruction += test_artifact_phase_context(issue.get('id'), task.get('agent_id'))
            try:import adapted_test_review
            except ImportError:from broker import adapted_test_review
            instruction += adapted_test_review.registered_author_context(handoff_context(),issue['id'],task)
            try:import surgical_recovery
            except ImportError:from broker import surgical_recovery
            surgical=surgical_recovery.for_task(handoff_context(),issue['id'],task)
            try:import driver_checkpoint_policy
            except ImportError:from broker import driver_checkpoint_policy
            driver=driver_checkpoint_policy.for_task(handoff_context(),issue['id'],task)
            try:import template_author_executor
            except ImportError:from broker import template_author_executor
            template=template_author_executor.for_task(handoff_context(),issue['id'],task)
            if template:
                if driver:raise ValueError('conflicting template/driver capabilities')
                driver=template
            if driver:
                if surgical:raise ValueError('conflicting surgical capabilities')
                surgical=driver['surgical']
            if surgical:
                version={'typed_v2':'V2','typed_driver_v3':'V3','typed_driver_lines_v4':'V4','typed_template_v5':'V5','typed_template_lines_v6':'V6'}.get(surgical.get('protocol'),'V1')
                instruction+='\nDELIVERY_SURGICAL_TEST_'+version+':'+surgical['path']+':'+surgical['expected_sha256']+'\n'
                if surgical.get('drain_resolver'):
                    instruction+='DELIVERY_STATUS_DRAIN_V1:'+surgical['drain_resolver']+'\n'
            try:import incremental_read_recovery
            except ImportError:from broker import incremental_read_recovery
            with db() as con:
                trial={}
                if con.execute("SELECT 1 FROM sqlite_master WHERE name='test_revision_trials'").fetchone():
                    trial=con.execute('SELECT config FROM test_revision_trials WHERE issue_id=?',(issue.get('id'),)).fetchone()
                    trial=json.loads(trial[0]) if trial else {}
                    if trial.get('seed_previous_tests') is True:
                        files=trial['old_red']['red']['test_sha256']
                        if len(files)!=1:raise ValueError('single seeded revision target required')
                        instruction+='\nDELIVERY_TEST_REVISION_V1:/workspace/'+next(iter(files))+'\n'
                        if trial.get('seeded_edit_required') is True:
                            instruction+='\nDELIVERY_SEEDED_EDIT_REQUIRED_V1:/workspace/'+next(iter(files))+'\n'
                        elif not surgical and 'DELIVERY_AUTHOR_READ_PAGE_V1:200' not in instruction:
                            instruction+='DELIVERY_AUTHOR_READ_PAGE_V1:200\n'
                if trial.get('harness_maintenance_only'):
                    try:import harness_repair_task
                    except ImportError:from broker import harness_repair_task
                    instruction=harness_repair_task.maintenance_prompt(instruction)
                if trial.get('harness_selector_experiment') or incremental_read_recovery.authorized(con,issue.get('id')):
                    instruction += '\nDELIVERY_DETERMINISTIC_READ_V1\n'
        elif phase == 'implement_after_red':
            instruction = ('IMPLEMENTATION PHASE. The controller has frozen the '
                           'test-only tree and executed Red. Implement only the declared '
                           'product-code paths in /workspace. Do not edit or replace any '
                           'tests. Do not replay Red. The controller will run the pinned '
                           'full suite and compare the final test bytes to frozen Red.')
    correction_text = ''
    if correction is not None:
        if mode != 'implementation' or not isinstance(correction.get('finding'), str) \
                or not 0 < len(correction['finding']) <= 600:
            raise ValueError('invalid verified correction')
        correction_text = (
            'CURRENT CONTROLLER-VERIFIED REVIEW REQUEST: The responsible technical/review owner '
            'has ALREADY requested this correction. Do not wait for another request. '
            'The original instruction to submit an intentionally incomplete first '
            'version no longer applies. Correct the existing workspace now, add '
            'the requested test without weakening prior tests, run the full suite, '
            'and submit a new revision. Review task: '
            + correction['review_task_id'] + '. Finding: ' + correction['finding'] + '\n\n')
    text = ('Controller-verified issue context. The Multica CLI is intentionally '
            'not configured inside this isolated worker; do not call it or search '
            'for credentials. The complete authorized task is below.\n\n'
            + correction_text +
            f'Issue: {title}\nDescription: {description}\n'
            f'Handoff note: {note}\n\n{instruction}')
    # Registered capsules bound description to 12k and the expanded note to
    # 16k. Reserve 4k for fixed controller instructions; never extend the
    # legacy limit for an unregistered issue or agent-provided marker.
    if len(text) > (32000 if capsule is not None else (16000 if mode == 'planning' else 10000)):
        raise ValueError('task prompt too large')
    rendered = {**frame, 'params': {**frame['params'],
            'prompt': [{'type': 'text', 'text': text}]}}
    if capsule is not None:
        try:from acp_transport import ControllerPrompt
        except ImportError:from broker.acp_transport import ControllerPrompt
        return ControllerPrompt(rendered,capsule)
    return rendered


def failure_category(error):
    if isinstance(error,DockerOperationTimeout):return 'docker_'+error.operation
    if isinstance(error, ValueError) and str(error) in {
            'bounded issue brief required', 'invalid handoff note', 'task prompt too large',
            'only bounded text prompts are qualified'}:
        return 'native_prompt_bounds'
    if str(error) == 'issue workspace seed failed':
        return 'workspace_seed'
    if str(error) == 'Docker did not upgrade stream':
        return 'worker_attach'
    if str(error) == 'ACP stream closed':
        return 'worker_stream_closed'
    if isinstance(error, TimeoutError):
        return 'prompt_timeout'
    if isinstance(error, (ConnectionError, BrokenPipeError)):
        return 'worker_transport'
    if isinstance(error, sqlite3.OperationalError):
        return 'broker_sqlite'
    if isinstance(error, subprocess.CalledProcessError):
        return 'worker_process'
    if isinstance(error, OSError):
        return 'worker_io'
    if isinstance(error, RuntimeError):
        known = {'ACP response size limit': 'acp_response_size',
                 'oversized Docker response': 'docker_response_size',
                 'invalid ACP frame': 'acp_invalid_frame',
                 'Docker did not upgrade stream': 'worker_attach',
                 'ACP stream closed': 'worker_stream_closed'}
        if str(error) in known:
            return known[str(error)]
        return 'broker_runtime'
    return 'broker_internal'


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass  # never log authorization headers or payloads

    def stream_message(self, authorization, payload):
        started = False
        def emit(kind, data):
            nonlocal started
            if not started:
                self.send_response(200)
                self.send_header('Content-Type', 'application/x-ndjson')
                self.send_header('Connection', 'close')
                self.end_headers()
                started = True
            self.wfile.write((json.dumps({'kind': kind, 'data': data}) + '\n').encode())
            self.wfile.flush()
        try:
            if not authorization.startswith('Bearer ') or payload.get('frame', {}).get('method') != 'session/prompt':
                raise ValueError('stream only accepts a capability-bound prompt')
            result = session_operation(authorization[7:], payload,
                                       on_notification=lambda frame: emit('notification', frame))
            # Receipts were persisted by session_operation before this removal.
            result.pop('_broker_notifications', None)
            emit('response', result)
        except Exception as error:
            category = failure_category(error)
            emit('error', {'category': category})
        self.close_connection = True

    def do_POST(self):
        status, response = 200, {}
        authorization = self.headers.get('Authorization', '')
        suite_call = self.path == '/v1/review-suite' and authorization.startswith('Bearer ')
        grant_call = self.path in ('/v1/acp-probe', '/v1/acp-open', '/v1/acp-message', '/v1/acp-message-stream', '/v1/acp-close') and authorization.startswith('Bearer ')
        if not grant_call and not suite_call and not hmac.compare_digest(authorization, 'Bearer ' + TOKEN):
            status, response = 401, {'error': 'unauthorized'}
        else:
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 16384:
                    raise ValueError('invalid body size')
                payload = json.loads(self.rfile.read(length))
                if self.path == '/v1/acp-message-stream':
                    self.stream_message(authorization, payload)
                    return
                if suite_call:
                    import review_suite_rpc
                    response = review_suite_rpc.execute(handoff_context(), authorization[7:], payload)
                elif grant_call:
                    if self.path in ('/v1/acp-message', '/v1/acp-close'):
                        response = session_operation(authorization[7:], payload, self.path == '/v1/acp-close')
                    else:
                        response = execute_grant(authorization[7:], payload, self.path == '/v1/acp-open')
                elif self.path == '/v1/grants':
                    response = issue_grant(payload)
                elif self.path == '/v1/native-grants':
                    response = native_grant(payload)
                elif self.path == '/v1/issue-bases':
                    response = register_issue_base(payload)
                elif self.path == '/v1/issue-editables':
                    response = register_issue_editables(payload)
                elif self.path == '/v1/issue-requirements':
                    response = register_issue_requirements(payload)
                elif self.path == '/v1/snapshots':
                    response = snapshot_submission(payload)
                elif self.path == '/v1/test-first-red':
                    response = capture_test_first_red(payload)
                elif self.path == '/v1/test-first-diagnostic-recovery':
                    import test_first_handoffs
                    response = test_first_handoffs.resume_diagnosis(handoff_context(), payload)
                elif self.path == '/v1/test-first-artifact-recovery':
                    import test_artifact_recovery
                    response = test_artifact_recovery.reopen(handoff_context(), payload)
                elif self.path == '/v1/test-first-provider-recovery':
                    import test_artifact_recovery
                    response = test_artifact_recovery.reopen_provider(handoff_context(), payload)
                elif self.path == '/v1/test-first-structural-replan':
                    import test_artifact_recovery
                    response = test_artifact_recovery.replan_structure(handoff_context(), payload)
                elif self.path == '/v1/test-first-transport-recovery':
                    import artifact_transport_recovery
                    response = artifact_transport_recovery.reopen(handoff_context(), payload)
                elif self.path == '/v1/test-first-integration-recovery':
                    import artifact_transport_recovery
                    response = artifact_transport_recovery.reopen_integration(handoff_context(), payload)
                elif self.path == '/v1/test-first-bootstrap-recovery':
                    import test_bootstrap_recovery
                    response = test_bootstrap_recovery.reopen(handoff_context(), payload)
                elif self.path == '/v1/test-first-format-recovery':
                    import test_bootstrap_recovery
                    response = test_bootstrap_recovery.reopen(handoff_context(), payload,normalized=True)
                elif self.path == '/v1/test-review-storage-recovery':
                    import test_revision_review
                    response=test_revision_review.resume_pagination(handoff_context(),payload,storage_repair=True)
                elif self.path == '/v1/review-assignments':
                    response = assign_review(payload)
                elif self.path == '/v1/review-policy-revalidation':
                    import review_revalidation
                    response = review_revalidation.reopen(handoff_context(), payload)
                elif self.path == '/v1/delivery-routes':
                    response = handoff_runtime.register(handoff_context(), payload)
                elif self.path == '/v1/reconcile-failed-suite':
                    import suite_diagnosis_repair
                    response = suite_diagnosis_repair.reopen(handoff_context(), payload)
                elif self.path == '/v1/failed-execution-diagnosis':
                    import failed_execution_diagnosis
                    response = failed_execution_diagnosis.register(handoff_context(), payload)
                elif self.path == '/v1/failed-execution-evidence':
                    import failed_execution_evidence
                    response = failed_execution_evidence.register(handoff_context(), payload)
                elif self.path == '/v1/candidate-qualification':
                    import candidate_qualification
                    response = candidate_qualification.register(handoff_context(), payload)
                elif self.path == '/v1/candidate-semantic-experiment':
                    import candidate_qualification
                    response = candidate_qualification.experiment(handoff_context(), payload)
                elif self.path == '/v1/candidate-semantic-revalidation':
                    import candidate_qualification
                    response = candidate_qualification.revalidate(handoff_context(), payload)
                elif self.path == '/v1/candidate-repair-findings':
                    import candidate_qualification
                    response = candidate_qualification.repair_findings(handoff_context(), payload)
                elif self.path == '/v1/test-review-semantic-revalidation':
                    import test_revision_review
                    response = test_revision_review.revalidate_semantics(handoff_context(), payload)
                elif self.path == '/v1/assertion-replan':
                    import assertion_replan
                    response = assertion_replan.register(handoff_context(), payload)
                elif self.path == '/v1/test-decomposition':
                    import test_decomposition
                    response = test_decomposition.register(handoff_context(), payload)
                elif self.path == '/v1/test-decomposition-transport-repair':
                    import test_decomposition
                    response = test_decomposition.repair_transport(handoff_context(), payload)
                elif self.path == '/v1/test-decomposition-stream-failure':
                    import test_decomposition
                    response = test_decomposition.capture_stream_failure(handoff_context(), payload)
                elif self.path == '/v1/execution-stall-recovery':
                    import execution_stall_recovery
                    response = execution_stall_recovery.register(handoff_context(), payload)
                elif self.path == '/v1/challenge-suite-diagnosis':
                    import suite_diagnosis_repair
                    response = suite_diagnosis_repair.challenge(handoff_context(), payload)
                elif self.path == '/v1/qa-diagnostic-artifacts':
                    import qa_artifacts
                    response = qa_artifacts.register(handoff_context(), payload)
                elif self.path == '/v1/test-revision-trials':
                    import test_revision_review
                    response = test_revision_review.register(handoff_context(), payload)
                elif self.path == '/v1/test-review-size-recovery':
                    import test_size_recovery
                    response = test_size_recovery.reopen(handoff_context(), payload)
                elif self.path == '/v1/test-review-evidence-challenge':
                    import test_review_challenge
                    response = test_review_challenge.reopen(handoff_context(), payload)
                elif self.path == '/v1/test-review-bootstrap-recovery':
                    import test_revision_review
                    response = test_revision_review.resume_bootstrap(handoff_context(), payload)
                elif self.path == '/v1/test-review-inspection-recovery':
                    import test_revision_review
                    response = test_revision_review.resume_inspection(handoff_context(), payload)
                elif self.path == '/v1/test-review-pagination-recovery':
                    import test_revision_review
                    response = test_revision_review.resume_pagination(handoff_context(), payload)
                elif self.path == '/v1/test-review-acp-recovery':
                    import test_revision_review
                    response = test_revision_review.resume_pagination(handoff_context(), payload, acp_repair=True)
                elif self.path == '/v1/candidate-corrections':
                    import candidate_correction
                    response = candidate_correction.register(handoff_context(), payload)
                elif self.path == '/v1/delivery-status' and set(payload) == {'issue_id'}:
                    with db() as con:
                        response = [dict(row) for row in con.execute(
                            'SELECT * FROM delivery_handoffs WHERE issue_id=? ORDER BY updated DESC',
                            (payload['issue_id'],))]
                elif self.path == '/v1/reviews':
                    response = record_review(payload)
                elif self.path == '/v1/probes':
                    response = submit(payload)
                elif self.path == '/v1/status' and set(payload) == {'request_id'}:
                    with LOCK, db() as con:
                        row = con.execute('SELECT * FROM leases WHERE request_id=?', (payload['request_id'],)).fetchone()
                        response = dict(row) if row else {'status': 'unknown'}
                else:
                    raise ValueError('unsupported operation')
            except (ValueError, TypeError, AttributeError):
                status, response = 400, {'error': 'invalid request'}
            except Exception as error:
                category = failure_category(error)
                if grant_call:
                    try:
                        with db() as con:
                            row = con.execute('SELECT request_id FROM grants WHERE digest=?',
                                              (hashlib.sha256(authorization[7:].encode()).hexdigest(),)).fetchone()
                            if row:
                                con.execute('INSERT INTO broker_errors VALUES (?,?,?,?)',
                                            (row['request_id'], self.path, category, time.time()))
                    except Exception:
                        pass  # diagnostic failure cannot disclose or replay a capability
                print(json.dumps({'event': 'broker_operation_failed',
                                  'operation': self.path, 'category': category}), flush=True)
                status, response = 503, {'error': 'broker operation failed', 'category': category}
        body = json.dumps(response).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    verify_worker_image()
    global TOKEN
    if not IMAGE.startswith('sha256:') or len(IMAGE) != 71:
        raise ValueError('immutable worker image ID required')
    STATE.mkdir(mode=0o700, exist_ok=True)
    token_path = STATE / 'token'
    if not token_path.exists():
        with os.fdopen(os.open(token_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as stream:
            stream.write(secrets.token_hex(32))
    TOKEN = token_path.read_text()
    with db() as con:
        con.execute('CREATE TABLE IF NOT EXISTS leases(request_id TEXT PRIMARY KEY, scenario TEXT, name TEXT, status TEXT, deadline REAL)')
        con.execute('CREATE TABLE IF NOT EXISTS grants(digest TEXT PRIMARY KEY, task_id TEXT, attempt INTEGER, mode TEXT, request_id TEXT, deadline REAL, used INTEGER, UNIQUE(task_id,attempt))')
        con.execute('CREATE TABLE IF NOT EXISTS native_bindings(request_id TEXT PRIMARY KEY, task_id TEXT, agent_id TEXT, scope TEXT, issue_id TEXT)')
        if 'issue_id' not in [row['name'] for row in con.execute('PRAGMA table_info(native_bindings)')]:
            con.execute('ALTER TABLE native_bindings ADD COLUMN issue_id TEXT')
        con.execute('CREATE TABLE IF NOT EXISTS issue_bases(issue_id TEXT PRIMARY KEY, base_sha TEXT, volume TEXT, manifest_sha256 TEXT)')
        con.execute('CREATE TABLE IF NOT EXISTS issue_editables(issue_id TEXT, path TEXT, PRIMARY KEY(issue_id,path))')
        con.execute('CREATE TABLE IF NOT EXISTS issue_test_commands(issue_id TEXT PRIMARY KEY, command TEXT)')
        con.execute('CREATE TABLE IF NOT EXISTS issue_requirements(issue_id TEXT, test_name TEXT, PRIMARY KEY(issue_id,test_name))')
        con.execute('CREATE TABLE IF NOT EXISTS review_findings(review_task_id TEXT PRIMARY KEY, finding TEXT)')
        con.execute('CREATE TABLE IF NOT EXISTS acp_sessions(scope TEXT, session_id TEXT, PRIMARY KEY(scope,session_id))')
        con.execute('CREATE TABLE IF NOT EXISTS acp_events(request_id TEXT, method TEXT, session_id TEXT, success INTEGER)')
        con.execute('CREATE TABLE IF NOT EXISTS tool_events(request_id TEXT, prompt_id TEXT, tool_count INTEGER, PRIMARY KEY(request_id,prompt_id))')
        con.execute('CREATE TABLE IF NOT EXISTS broker_errors(request_id TEXT, operation TEXT, category TEXT, at REAL)')
        con.execute('CREATE TABLE IF NOT EXISTS snapshots(task_id TEXT PRIMARY KEY, volume TEXT, status TEXT)')
        con.execute('CREATE TABLE IF NOT EXISTS test_first_red('
                    'issue_id TEXT PRIMARY KEY, task_id TEXT UNIQUE, scope TEXT, volume TEXT, receipt TEXT)')
        con.execute('CREATE TABLE IF NOT EXISTS review_assignments(review_agent_id TEXT PRIMARY KEY, source_task_id TEXT, volume TEXT)')
        con.execute('CREATE TABLE IF NOT EXISTS review_bindings(request_id TEXT PRIMARY KEY, source_task_id TEXT, volume TEXT)')
        con.execute('CREATE TABLE IF NOT EXISTS reviews(review_task_id TEXT PRIMARY KEY, source_task_id TEXT, reviewer_agent_id TEXT, manifest_sha256 TEXT, status TEXT)')
        con.execute('CREATE TABLE IF NOT EXISTS review_incidents(review_task_id TEXT PRIMARY KEY, reason TEXT, status TEXT, created_at REAL)')
        con.execute('CREATE TABLE IF NOT EXISTS review_retry_attempts(review_task_id TEXT PRIMARY KEY, attempts INTEGER)')
        con.execute('CREATE TABLE IF NOT EXISTS review_retry_wakeups(review_task_id TEXT PRIMARY KEY, wakeup_id TEXT)')
        con.execute('CREATE TABLE IF NOT EXISTS change_handoffs(review_task_id TEXT PRIMARY KEY, reviewer_wakeup_id TEXT, implementer_wakeup_id TEXT)')
        con.execute('CREATE TABLE IF NOT EXISTS change_requirements(issue_id TEXT, review_task_id TEXT, test_name TEXT, PRIMARY KEY(issue_id,review_task_id,test_name))')
        con.execute('CREATE TABLE IF NOT EXISTS change_handoff_failures(review_task_id TEXT PRIMARY KEY, attempts INTEGER, error_type TEXT)')
        handoff_runtime.initialize(con)
        con.execute("UPDATE review_incidents SET status='legacy_unqualified' "
                    "WHERE reason='review snapshot assignment missing' AND review_task_id NOT IN "
                    "(SELECT n.task_id FROM native_bindings n JOIN review_bindings b USING(request_id))")
        # Restart fences old executions instead of assuming they successfully resumed.
        for row in con.execute("SELECT * FROM leases WHERE status IN ('creating','running')").fetchall():
            remove_owned(row['name'], row['request_id'])
            con.execute("UPDATE leases SET status='interrupted' WHERE request_id=?", (row['request_id'],))
    def watchdog():
        cycle = 0
        while True:
            try:
                tick()
                cycle += 1
                if cycle % 10 == 0:
                    reconcile_review_outcomes()
                    reconcile_review_retries()
                    reconcile_change_requests()
                    import candidate_qualification
                    candidate_qualification.tick(handoff_context())
                    import assertion_replan
                    assertion_replan.tick(handoff_context())
                    import technical_remediation_plan
                    technical_remediation_plan.tick(handoff_context())
                    import test_decomposition
                    test_decomposition.tick(handoff_context())
                    import u3_controls_execution
                    u3_controls_execution.tick(handoff_context())
                    import u3_product_intake
                    u3_product_intake.tick(handoff_context())
                    import u3_coverage_integration
                    u3_coverage_integration.tick(handoff_context())
                    import u3_delivery_review
                    u3_delivery_review.tick(handoff_context())
                    import harness_prerequisite
                    harness_prerequisite.tick(handoff_context())
                    import harness_repair_task
                    harness_repair_task.tick(handoff_context())
                    import incremental_supervisor
                    incremental_supervisor.tick(handoff_context())
                    handoff_runtime.tick(handoff_context())
                    import inherited_test_replan
                    inherited_test_replan.tick(handoff_context())
            except Exception:
                print('watchdog reconciliation failed; leases remain visible', flush=True)
            time.sleep(1)
    import helper_cleanup
    threading.Thread(target=helper_cleanup.run,args=(handoff_context(),),daemon=True).start()
    if os.environ.get('BROKER_QA_CLEANUP_OBSERVER') == '1':
        import qa_cleanup_observer
        threading.Thread(target=qa_cleanup_observer.run,args=(handoff_context(),),daemon=True).start()
    threading.Thread(target=watchdog, daemon=True).start()
    print('evaluation broker ready; fixed offline probes only', flush=True)
    ThreadingHTTPServer(('0.0.0.0', 8090), Handler).serve_forever()


if __name__ == '__main__':
    main()
