"""Bounded ACP inference in one disposable, credential-free Hermes worker."""
import json
import selectors
import subprocess
import time
import uuid

from evalctl import ROOT, process_env
from register_team import MODEL


def main():
    name = 'delivery-kit-eval-model-acp-' + uuid.uuid4().hex[:12]
    command = ['docker', 'run', '--rm', '-i', '--name', name,
               *__import__('docker_grouping').args('acp-smoke'),
               '--label', 'delivery-kit.owner=delivery-kit-eval-model-smoke',
               '--network', 'delivery-kit-eval_model', '--read-only', '--user', '10000:10000',
               '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
               '--pids-limit', '128', '--memory', '512m', '--cpus', '1',
               '--tmpfs', '/tmp:rw,nosuid,nodev,size=64m,mode=1777',
               '--env', 'HOME=/tmp', '--env', 'HERMES_HOME=/tmp/hermes',
               '--env', 'OPENROUTER_API_KEY=offline-placeholder-not-a-credential',
               '--env', 'OPENROUTER_BASE_URL=http://model-proxy:8080/api/v1',
               '--workdir', '/delivery',
               '--mount', f'type=bind,source={ROOT / "tests/fixtures/delivery"},target=/delivery,readonly',
               '--entrypoint', 'python', 'delivery-kit-eval-broker:20260923.3',
               '/worker_model_config.py']
    process = None
    try:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, env=process_env())
        pending = b''
        notifications = []
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            def call(request_id, method, params, timeout=90):
                nonlocal pending
                process.stdin.write((json.dumps({'jsonrpc': '2.0', 'id': request_id,
                    'method': method, 'params': params}) + '\n').encode())
                process.stdin.flush()
                deadline = time.monotonic() + timeout
                while time.monotonic() < deadline:
                    for key, _ in selector.select(timeout=1):
                        chunk = key.fileobj.read1(65536)
                        if not chunk:
                            raise RuntimeError('ACP closed before ' + method)
                        pending += chunk
                        if len(pending) > 4 * 1024 * 1024:
                            raise RuntimeError('ACP output bound exceeded')
                        while b'\n' in pending:
                            line, pending = pending.split(b'\n', 1)
                            try:
                                frame = json.loads(line)
                            except json.JSONDecodeError:
                                continue
                            if frame.get('id') == request_id:
                                if 'error' in frame:
                                    raise RuntimeError(method + ': ACP error code ' +
                                                       str(frame['error'].get('code')))
                                return frame.get('result', {})
                            if frame.get('method') == 'session/update':
                                notifications.append(frame)
                            if 'method' in frame and 'id' in frame:
                                process.stdin.write((json.dumps({'jsonrpc': '2.0',
                                    'id': frame['id'], 'error': {'code': -32601,
                                    'message': 'client-side tools disabled'}}) + '\n').encode())
                                process.stdin.flush()
                raise TimeoutError(method)
            call(1, 'initialize', {'protocolVersion': 1, 'clientCapabilities': {},
                                   'clientInfo': {'name': 'isolated-model-smoke', 'version': '1'}}, 30)
            session = call(2, 'session/new', {'cwd': '/delivery', 'mcpServers': [], 'model': MODEL}, 30)
            sid = session['sessionId']
            call(3, 'session/set_model', {'sessionId': sid, 'modelId': MODEL}, 30)
            response = call(4, 'session/prompt', {'sessionId': sid,
                'prompt': [{'type': 'text', 'text': 'Reply with exactly READY. Do not use tools.'}]}, 120)
            assistant_text = ''.join(str((frame.get('params', {}).get('update', {}).get('content') or {}).get('text') or '')
                                     for frame in notifications)
            print(json.dumps({'acp_prompt_completed': True,
                              'stop_reason': response.get('stopReason'),
                              'assistant_text': assistant_text[:160],
                              'worker_has_provider_key': False,
                              'worker_has_docker_socket': False}))
            if 'READY' not in assistant_text or 'API call failed' in assistant_text:
                raise RuntimeError('ACP did not produce a model response')
    finally:
        subprocess.run(['docker', 'rm', '-f', name], capture_output=True, timeout=10,
                       env=process_env())
        if process:
            process.communicate(timeout=10)


if __name__ == '__main__':
    main()
