"""Real fixed-probe lifecycle test. No provider keys, Multica tasks or product files."""
import json
import subprocess
import time
import uuid
from evalctl import ROOT, ENV_FILE, PROJECT, process_env

CONTAINER = 'delivery-kit-eval-execution-broker-1'
CLIENT = '''import json,sys,urllib.request,urllib.error
from pathlib import Path
p=json.load(sys.stdin)
key=Path('/broker-state/token').read_text() if p['authorized'] else 'invalid'
r=urllib.request.Request('http://127.0.0.1:8090'+p['path'],data=json.dumps(p['body']).encode(),headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
try:
 with urllib.request.urlopen(r,timeout=15) as s: print(json.dumps({'code':s.status,'body':json.load(s)}))
except urllib.error.HTTPError as e: print(json.dumps({'code':e.code}))
'''


def api(path, body, authorized=True):
    output = subprocess.check_output(['docker', 'exec', '-i', CONTAINER, 'python', '-c', CLIENT],
        input=json.dumps(dict(path=path, body=body, authorized=authorized)), text=True,
        timeout=20, env=process_env(), stderr=subprocess.PIPE)
    return json.loads(output)


def wait(request_id, expected, timeout=55):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        response = api('/v1/status', {'request_id': request_id})
        if response['body']['status'] == expected:
            return
        if response['body']['status'] not in ('running', 'creating'):
            raise RuntimeError('unexpected terminal state: ' + response['body']['status'])
        time.sleep(1)
    raise TimeoutError(expected)


def main():
    image = subprocess.check_output(['docker', 'image', 'inspect', '--format', '{{.Id}}',
                                    'delivery-kit-eval-broker:20260923.3'], text=True).strip()
    env = {**process_env(), 'BROKER_WORKER_IMAGE': image}
    subprocess.run(['docker', 'compose', '--project-name', PROJECT,
                    '--env-file', str(ENV_FILE), '-f', str(ROOT / 'compose.eval.yaml'),
                    '-f', str(ROOT / 'compose.runtime.yaml'), '-f', str(ROOT / 'compose.broker.yaml'),
                    '--profile', 'runtime', 'up', '-d', '--no-deps', 'execution-broker'], env=env, check=True)
    for attempt in range(10):
        try:
            assert api('/v1/probes', {}, False)['code'] == 401
            break
        except subprocess.CalledProcessError:
            if attempt == 9:
                raise
            time.sleep(1)
    assert api('/v1/probes', {'request_id': str(uuid.uuid4()), 'scenario': 'canary', 'command': 'id'})['code'] == 400
    first = {'request_id': str(uuid.uuid4()), 'scenario': 'canary'}
    one = api('/v1/probes', first)
    two = api('/v1/probes', first)
    assert one['body']['name'] == two['body']['name']
    wait(first['request_id'], 'passed')
    lease = {'request_id': str(uuid.uuid4()), 'scenario': 'lease'}
    assert api('/v1/probes', lease)['code'] == 200
    second = {'request_id': str(uuid.uuid4()), 'scenario': 'lease'}
    assert api('/v1/probes', second)['code'] == 200
    assert api('/v1/probes', {'request_id': str(uuid.uuid4()), 'scenario': 'lease'})['code'] == 400
    print('PASS: auth, restricted input, canary, idempotency, two-slot capacity', flush=True)
    subprocess.run(['docker', 'restart', CONTAINER], check=True, capture_output=True, timeout=30)
    time.sleep(2)
    wait(lease['request_id'], 'interrupted')
    wait(second['request_id'], 'interrupted')
    assert api('/v1/probes', lease)['body']['status'] == 'interrupted'
    for payload in (lease, second):
        name = 'delivery-kit-eval-job-' + payload['request_id']
        assert subprocess.run(['docker', 'inspect', name], capture_output=True).returncode != 0
    print('PASS: restart cleanup, durable interrupted receipt, no implicit retry', flush=True)
    expiry = {'request_id': str(uuid.uuid4()), 'scenario': 'lease'}
    assert api('/v1/probes', expiry)['code'] == 200
    wait(expiry['request_id'], 'expired')
    assert subprocess.run(['docker', 'inspect', 'delivery-kit-eval-job-' + expiry['request_id']], capture_output=True).returncode != 0
    print('PASS: disconnected client lease expires and container removed', flush=True)


if __name__ == '__main__':
    main()
