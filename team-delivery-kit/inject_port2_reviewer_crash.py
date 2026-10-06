"""One-shot port2 fault: stop only a verified ephemeral reviewer worker."""
import argparse
import json
import subprocess
import time


PREFIX = 'delivery-kit-port2'
BROKER = PREFIX + '-execution-broker-1'
OWNER = PREFIX + '-broker-v1'


def command(*args):
    return subprocess.check_output(args, text=True, timeout=15).strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--label', choices=('PORT-8', 'PORT-9'), required=True)
    label = parser.parse_args().label
    reviewer = json.load(open('.local-port2/portable-reviewer-v2.json'))['agent_id']
    marker = json.load(open('.local-port2/portable-context-' + label + '.json'))['issue_id']
    deadline = time.monotonic() + 300
    seen = set()
    while time.monotonic() < deadline:
        names = command('docker', 'ps', '--filter', 'label=delivery-kit.owner=' + OWNER,
                        '--format', '{{.Names}}').splitlines()
        for name in names:
            if name in seen or not name.startswith(PREFIX + '-job-'):
                continue
            seen.add(name)
            info = json.loads(command('docker', 'inspect', name))[0]
            labels = info['Config']['Labels']
            if labels.get('delivery-kit.owner') != OWNER or not info['State']['Running']:
                continue
            request_id = labels.get('delivery-kit.request')
            if name != PREFIX + '-job-' + request_id:
                continue
            query = ('import sqlite3,json,sys; '
                     'c=sqlite3.connect("file:/broker-state/leases.sqlite?mode=ro",uri=True); '
                     'r=c.execute("SELECT agent_id,issue_id,task_id FROM native_bindings '
                     'WHERE request_id=?",(sys.argv[1],)).fetchone(); '
                     'print(json.dumps(r))')
            binding = json.loads(command('docker', 'exec', BROKER, 'python', '-c',
                                         query, request_id))
            if binding and binding[0] == reviewer and binding[1] == marker:
                # Inspect again immediately before the exact-ID stop.
                checked = json.loads(command('docker', 'inspect', info['Id']))[0]
                if (checked['Config']['Labels'] != labels or
                        not checked['State']['Running']):
                    raise RuntimeError('reviewer worker identity changed')
                subprocess.run(['docker', 'kill', info['Id']], check=True,
                               capture_output=True, timeout=15)
                print(json.dumps({'fault_injected': True, 'issue_id': marker,
                                  'task_id': binding[2], 'request_id': request_id}), flush=True)
                return
        time.sleep(0.2)
    raise TimeoutError(label + ' reviewer worker did not appear within five minutes')


if __name__ == '__main__':
    main()
