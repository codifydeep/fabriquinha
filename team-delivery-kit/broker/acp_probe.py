"""Fixed in-sandbox ACP check. No prompt, model, network or controller credentials."""
import json
import os
import selectors
import subprocess
import time
from pathlib import Path

process = subprocess.Popen(['hermes', 'acp'], stdin=subprocess.PIPE,
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
request = {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
           'params': {'protocolVersion': 1, 'clientCapabilities': {},
                      'clientInfo': {'name': 'broker-offline-probe', 'version': '1'}}}
try:
    process.stdin.write((json.dumps(request) + '\n').encode())
    process.stdin.flush()
    response, pending = {}, b''
    deadline = time.monotonic() + 25
    with selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ)
        while not response and time.monotonic() < deadline:
            for key, _ in selector.select(timeout=1):
                chunk = key.fileobj.read1(65536)
                if not chunk:
                    raise RuntimeError('unexpected ACP EOF')
                pending += chunk
                while b'\n' in pending:
                    line, pending = pending.split(b'\n', 1)
                    try:
                        frame = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(frame, dict) and frame.get('id') == 1:
                        response = frame
    assert response.get('result', {}).get('protocolVersion') == 1
    assert not Path('/broker-state/token').exists()
    assert not Path('/eval-state/.multica/config.json').exists()
    assert not Path('/var/run/docker.sock').exists()
    print(json.dumps({'acp_initialized': True, 'uid': os.getuid(), 'model_called': False}), flush=True)
finally:
    process.kill()
    process.communicate(timeout=5)
