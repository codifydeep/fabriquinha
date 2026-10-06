"""Bounded ACP transport over Docker exec. No host commands or credential forwarding."""
import json
import socket
import struct
import time
import threading
from pathlib import PurePosixPath

from model_policy import MODEL, PROXY_BASE_URL, PLACEHOLDER_KEY, execution_base_url


def worker_env(mode, persistent, test_commands=(), review_suite_capability=None, execution_id=None):
    if mode not in ('review', 'implementation', 'planning'):
        raise ValueError('invalid execution mode')
    values = ['HOME=/tmp', 'HERMES_HOME=' + ('/session-state' if persistent else '/tmp/hermes'),
              'OPENROUTER_API_KEY=' + PLACEHOLDER_KEY,
              'OPENROUTER_BASE_URL=' + (execution_base_url(execution_id) if execution_id else PROXY_BASE_URL)]
    if execution_id:
        values.append('DELIVERY_MODEL_EXECUTION_ID=' + execution_id)
    values += ['DELIVERY_EXECUTION_MODE=' + mode,
               'DELIVERY_TEST_COMMANDS_JSON=' + json.dumps(list(test_commands))]
    if review_suite_capability:
        if mode != 'review' or len(review_suite_capability) != 64:
            raise ValueError('invalid review suite capability scope')
        values.append('DELIVERY_REVIEW_SUITE_CAPABILITY=' + review_suite_capability)
    if mode == 'implementation':
        values.append('HERMES_WRITE_SAFE_ROOT=/workspace')
        values.append('HERMES_FENCED_INPLACE_WRITES=1')
    return values


def permission_response(request, mode, editable_paths=frozenset(), test_commands=frozenset()):
    """Allow one edit of exactly one disposable file; never persist grants."""
    identifier = request.get('id')
    params = request.get('params')
    options = params.get('options') if isinstance(params, dict) else None
    if not isinstance(options, list):
        options = []
    reject = next((o['optionId'] for o in options if isinstance(o, dict)
                   and o.get('kind') == 'reject_once' and isinstance(o.get('optionId'), str)), None)
    allow = next((o['optionId'] for o in options if isinstance(o, dict)
                  and o.get('kind') == 'allow_once' and o.get('optionId') == 'allow_once'), None)
    tool = params.get('toolCall') if isinstance(params, dict) else None
    if isinstance(tool, dict):
        raw = tool.get('rawInput')
        command = raw.get('command') if isinstance(raw, dict) else None
        if (mode == 'implementation' and allow and tool.get('kind') == 'execute'
                and isinstance(command, str) and command in test_commands
                and isinstance(tool.get('title'), str)
                and tool['title'].endswith(command)):
            return {'jsonrpc': '2.0', 'id': identifier,
                    'result': {'outcome': {'outcome': 'selected', 'optionId': allow}}}
        title = tool.get('title')
        content = tool.get('content')
        if isinstance(title, str) and title.startswith('Approve edit: ') and isinstance(content, list):
            path = title.removeprefix('Approve edit: ')
            paths = [item.get('path') for item in content if isinstance(item, dict) and item.get('type') == 'diff']
            if (mode == 'implementation' and allow and path in editable_paths
                    and str(PurePosixPath(path)) == path and paths == [path]
                    and tool.get('kind') == 'edit'):
                return {'jsonrpc': '2.0', 'id': identifier,
                        'result': {'outcome': {'outcome': 'selected', 'optionId': allow}}}
    if reject:
        return {'jsonrpc': '2.0', 'id': identifier,
                'result': {'outcome': {'outcome': 'selected', 'optionId': reject}}}
    return {'jsonrpc': '2.0', 'id': identifier,
            'error': {'code': -32603, 'message': 'no safe permission option'}}


class Transport:
    def __init__(self, docker, name, persistent=False, mode='review', editable_paths=(),
                 test_commands=(), review_suite_capability=None):
        if mode not in ('review', 'implementation', 'planning'):
            raise ValueError('invalid execution mode')
        self.mode = mode
        self.editable_paths = frozenset(editable_paths)
        self.test_commands = frozenset(test_commands)
        self.cwd = ('/workspace' if mode == 'implementation' else
                    '/delivery' if mode == 'review' else '/tmp')
        execution = docker('POST', '/containers/' + name + '/exec', {
            'AttachStdin': True, 'AttachStdout': True, 'AttachStderr': True,
            'Tty': False, 'User': '10000:10000', 'Cmd': ['python', '/worker_model_config.py'],
            # Explicit offline marker, not a usable credential. Container network is none
            # and the ACP policy rejects every prompt. This only permits session setup.
            'Env': worker_env(mode, persistent, self.test_commands, review_suite_capability,
                              name.rsplit('-job-', 1)[1]),
            'WorkingDir': self.cwd})
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(25)
        self.sock.connect('/var/run/docker.sock')
        body = b'{"Detach":false,"Tty":false}'
        request = (f'POST /v1.45/exec/{execution["Id"]}/start HTTP/1.1\r\n'
                   'Host: localhost\r\nConnection: Upgrade\r\nUpgrade: tcp\r\n'
                   f'Content-Type: application/json\r\nContent-Length: {len(body)}\r\n\r\n').encode()
        self.sock.sendall(request + body)
        header = b''
        while not header.endswith(b'\r\n\r\n'):
            header += self.read_exact(1)
            if len(header) > 8192:
                raise RuntimeError('oversized Docker response')
        if not header.startswith(b'HTTP/1.1 101'):
            self.close()
            raise RuntimeError('Docker did not upgrade stream')
        self.pending = b''
        self.lock = threading.Lock()
        self.stderr_tail = b''
        self.model_selected = False

    def read_exact(self, size, deadline=None):
        result = b''
        while len(result) < size:
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError('ACP reply deadline')
                self.sock.settimeout(remaining)
            chunk = self.sock.recv(size - len(result))
            if not chunk:
                raise RuntimeError('ACP stream closed')
            result += chunk
        return result

    def exchange(self, frame, on_notification=None):
        if not self.lock.acquire(blocking=False):
            raise ValueError('one outstanding ACP request per execution')
        try:
            return self._exchange(frame, on_notification)
        finally:
            self.lock.release()

    def _exchange(self, frame, on_notification=None):
        validate_frame(frame)
        # No terminal/fs/MCP client capabilities and no arbitrary host cwd.
        forwarded = dict(frame)
        if frame['method'] == 'initialize':
            forwarded['params'] = {'protocolVersion': 1, 'clientCapabilities': {},
                                   'clientInfo': {'name': 'delivery-kit-isolated', 'version': '1'}}
        elif frame['method'] in ('session/new', 'session/resume'):
            forwarded['params'] = {'cwd': self.cwd, 'mcpServers': []}
            if frame['method'] == 'session/resume':
                forwarded['params']['sessionId'] = frame['params']['sessionId']
            elif frame.get('params', {}).get('model') == MODEL:
                forwarded['params']['model'] = MODEL
        else:
            if frame['method'] == 'session/prompt' and not self.model_selected:
                raise ValueError('model must be selected before prompt')
            forwarded['params'] = frame['params']
        self.sock.sendall((json.dumps(forwarded) + '\n').encode())
        prompt = frame['method'] == 'session/prompt'
        started = time.monotonic()
        deadline = started + (1800 if prompt else 25)
        idle_deadline = started + (300 if prompt else 25)
        total = 0
        notifications = []
        while time.monotonic() < min(deadline, idle_deadline):
            read_deadline = min(deadline, idle_deadline)
            header = self.read_exact(8, read_deadline)
            size = struct.unpack('>I', header[4:])[0]
            total += size
            # A full TDD run can emit several megabytes of bounded tool updates.
            if total > 8 * 1024 * 1024:
                raise RuntimeError('ACP response size limit')
            chunk = self.read_exact(size, read_deadline)
            if time.monotonic() >= read_deadline:
                raise TimeoutError('ACP reply deadline')
            if header[0] != 1:
                self.stderr_tail = (self.stderr_tail + chunk)[-8192:]
                continue  # stderr never becomes protocol or credential-bearing public logs
            self.pending += chunk
            while b'\n' in self.pending:
                line, self.pending = self.pending.split(b'\n', 1)
                try:
                    result = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(result, dict):
                    raise RuntimeError('invalid ACP frame')
                if 'method' in result and 'id' in result:
                    # Never execute a request on the privileged daemon/broker.
                    reply = (permission_response(result, self.mode, self.editable_paths,
                                                 self.test_commands)
                             if result['method'] == 'session/request_permission'
                             else {'jsonrpc': '2.0', 'id': result['id'],
                                   'error': {'code': -32601, 'message': 'client-side tools disabled'}})
                    self.sock.sendall((json.dumps(reply) + '\n').encode())
                    if prompt and result['method'] == 'session/request_permission':
                        idle_deadline = time.monotonic() + 300
                elif 'method' in result and result['method'] == 'session/update':
                    if prompt:
                        idle_deadline = time.monotonic() + 300
                    notifications.append(result)
                    if on_notification is not None:
                        on_notification(result)
                elif result.get('id') == frame['id']:
                    if 'error' in result:
                        diagnostic = self.stderr_tail.decode(errors='replace').lower()
                        result['error']['data'] = {'broker_diagnostic': [label for text, label in (
                            ('api key', 'provider_configuration'),
                            ('api_key', 'provider_configuration'),
                            ('read-only', 'readonly_filesystem'),
                            ('permission denied', 'filesystem_permission'),
                            ('modulenotfounderror', 'missing_dependency'),
                        ) if text in diagnostic]}
                    elif frame['method'] == 'session/new' and frame.get('params', {}).get('model') == MODEL:
                        self.model_selected = True
                    elif frame['method'] == 'session/set_model':
                        self.model_selected = True
                    result['_broker_notifications'] = notifications
                    return result
        raise TimeoutError('ACP reply deadline')

    def close(self):
        self.sock.close()


def validate_frame(frame):
    if not isinstance(frame, dict) or set(frame) - {'jsonrpc', 'id', 'method', 'params'}:
        raise ValueError('invalid ACP frame')
    if frame.get('jsonrpc') != '2.0' or type(frame.get('id')) not in (str, int):
        raise ValueError('request identity required')
    method = frame.get('method')
    if method not in ('initialize', 'session/new', 'session/resume', 'session/set_model', 'session/prompt'):
        raise ValueError('ACP method not qualified')
    params = frame.get('params', {})
    if not isinstance(params, dict):
        raise ValueError('invalid ACP parameters')
    if method == 'session/new' and params.get('model') not in (None, MODEL):
        raise ValueError('unapproved model')
    if method == 'session/set_model' and (set(params) != {'sessionId', 'modelId'} or params['modelId'] != MODEL):
        raise ValueError('unapproved model change')
    if method == 'session/prompt':
        prompt = params.get('prompt')
        if (set(params) != {'sessionId', 'prompt'} or not isinstance(prompt, list) or
                len(prompt) != 1 or not isinstance(prompt[0], dict) or
                set(prompt[0]) != {'type', 'text'} or prompt[0]['type'] != 'text' or
                not isinstance(prompt[0]['text'], str) or
                not 0 < len(prompt[0]['text']) <= 12000):
            raise ValueError('only bounded text prompts are qualified')
