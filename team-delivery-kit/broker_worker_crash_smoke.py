"""Port2-only offline probe: a killed leased worker must fail and be removed."""
import json
import subprocess
import time
import uuid


BROKER = 'delivery-kit-port2-execution-broker-1'
PREFIX = 'delivery-kit-port2'
OWNER = PREFIX + '-broker-v1'
CLIENT = '''import json,sys,urllib.request,urllib.error
from pathlib import Path
p=json.load(sys.stdin)
key=Path('/broker-state/token').read_text()
r=urllib.request.Request('http://127.0.0.1:8090'+p['path'],data=json.dumps(p['body']).encode(),headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
try:
 with urllib.request.urlopen(r,timeout=15) as s: print(json.dumps({'code':s.status,'body':json.load(s)}))
except urllib.error.HTTPError as e: print(json.dumps({'code':e.code}))
'''


def api(path, body):
    output = subprocess.check_output(
        ['docker', 'exec', '-i', BROKER, 'python', '-c', CLIENT],
        input=json.dumps({'path': path, 'body': body}), text=True, timeout=20)
    return json.loads(output)


def inspect(name):
    result = subprocess.run(['docker', 'inspect', name], text=True,
                            capture_output=True, timeout=20)
    if result.returncode:
        return None
    return json.loads(result.stdout)[0]


def main():
    broker = inspect(BROKER)
    if not broker or not broker['State']['Running']:
        raise RuntimeError('port2 broker unavailable')
    if broker['Config']['Labels'].get('com.docker.compose.project') != PREFIX:
        raise RuntimeError('port2 broker identity mismatch')
    request_id = str(uuid.uuid4())
    payload = {'request_id': request_id, 'scenario': 'lease'}
    response = api('/v1/probes', payload)
    if response['code'] != 200:
        raise RuntimeError('probe rejected: ' + str(response['code']))
    name = PREFIX + '-job-' + request_id
    if response['body'].get('name') != name:
        raise RuntimeError('probe container identity mismatch')
    worker = inspect(name)
    labels = worker['Config']['Labels'] if worker else {}
    if (not worker or not worker['State']['Running'] or
            labels.get('delivery-kit.owner') != OWNER or
            labels.get('delivery-kit.request') != request_id or
            labels.get('com.docker.compose.project') != PREFIX):
        raise RuntimeError('probe worker ownership mismatch; no container stopped')
    subprocess.run(['docker', 'kill', name], check=True, capture_output=True,
                   text=True, timeout=20)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        state = api('/v1/status', {'request_id': request_id})
        if state['code'] == 200 and state['body'].get('status') == 'failed':
            break
        time.sleep(1)
    else:
        raise RuntimeError('broker did not report killed worker as failed')
    if inspect(name) is not None:
        raise RuntimeError('failed worker container not removed')
    repeated = api('/v1/probes', payload)
    if repeated['code'] != 200 or repeated['body'].get('status') != 'failed':
        raise RuntimeError('probe replay did not preserve failed receipt')
    print(json.dumps({'result': 'passed', 'request_id': request_id,
                      'broker_status': 'failed', 'container_removed': True,
                      'replay_did_not_restart_worker': True}))


if __name__ == '__main__':
    main()
