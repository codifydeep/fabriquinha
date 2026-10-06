"""Offline ACP transport probe, not a task broker or runtime registration."""
import json
import subprocess
import selectors
import time
import uuid
from evalctl import ROOT, process_env
from docker_grouping import args as docker_group_args


def main():
    name = 'delivery-kit-eval-acp-' + uuid.uuid4().hex[:12]
    command = [
        'docker', 'run', '--rm', '-i', '--name', name,
        *docker_group_args('acp-probe',namespace='delivery-kit-eval'),
        '--network', 'none', '--read-only', '--user', '10000:10000',
        '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
        '--pids-limit', '128', '--memory', '512m', '--cpus', '1',
        '--tmpfs', '/tmp:rw,nosuid,nodev,size=32m,mode=1777',
        '--tmpfs', '/agent-home:rw,nosuid,nodev,size=32m,mode=1777',
        '--env', 'HOME=/agent-home', '--env', 'HERMES_HOME=/agent-home/hermes',
        '--workdir', '/delivery',
        '--mount', f'type=bind,source={ROOT / "tests/fixtures/delivery"},target=/delivery,readonly',
        '--entrypoint', 'hermes', 'delivery-kit-hermes-runtime:20260921.1', 'acp',
    ]
    request = {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
               'params': {'protocolVersion': 1, 'clientCapabilities': {},
                          'clientInfo': {'name': 'offline-boundary-probe', 'version': '1'}}}
    process = None
    try:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, env=process_env())
        process.stdin.write((json.dumps(request) + '\n').encode())
        process.stdin.flush()
        response, pending = {}, b''
        deadline = time.monotonic() + 30
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while not response and time.monotonic() < deadline:
                for key, _ in selector.select(timeout=1):
                    chunk = key.fileobj.read1(65536)
                    if not chunk:
                        raise RuntimeError('ACP exited before initialization response')
                    pending += chunk
                    while b'\n' in pending:
                        line, pending = pending.split(b'\n', 1)
                        try:
                            frame = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if isinstance(frame, dict) and frame.get('id') == 1:
                            response = frame
        result = response.get('result', {})
        passed = bool(result.get('protocolVersion')) and 'error' not in response
        print(json.dumps({'initialize_passed': passed,
                          'protocol_version': result.get('protocolVersion'),
                          'agent_info': result.get('agentInfo'),
                          'model_called': False, 'multica_dispatch_tested': False}))
        if not passed:
            raise RuntimeError('ACP initialization failed; no qualification')
    finally:
        # Exact unique disposable target only; handles a CLI timeout leaving Docker alive.
        subprocess.run(['docker', 'rm', '-f', name], capture_output=True,
                       timeout=10, env=process_env())
        if process:
            process.communicate(timeout=10)


if __name__ == '__main__':
    main()
