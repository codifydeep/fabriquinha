"""Credential-free host entrypoint for the operator-only broker maintenance barrier."""
import argparse
import json
import re
import subprocess
import uuid

PROGRAM = '''import sys;sys.path.insert(0,"/")
import broker as b,json,controller_maintenance as m
action,operation=sys.argv[1:]
if action=="status":
 with b.db() as con: value=m.current(con)
else: value={"drain":m.begin,"seal":m.seal,"release":m.release}[action](b,operation)
print(json.dumps(value,sort_keys=True))
'''


def arguments(namespace, action, operation):
    if not re.fullmatch(r'delivery-kit-[a-z0-9-]{1,48}', namespace):
        raise ValueError('exact delivery-kit namespace required')
    if action not in ('status', 'drain', 'seal', 'release'): raise ValueError('fixed maintenance action required')
    if action != 'status' and str(uuid.UUID(operation)) != operation:
        raise ValueError('canonical operation identity required')
    return ['docker', 'exec', '-w', '/', namespace+'-execution-broker-1',
            'python', '-c', PROGRAM, action, operation]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--namespace', required=True)
    parser.add_argument('--action', choices=('status', 'drain', 'seal', 'release'), required=True)
    parser.add_argument('--operation', default='')
    args = parser.parse_args()
    command = arguments(args.namespace, args.action, args.operation)
    # An exact name alone is insufficient to select an administrative target.
    labels = json.loads(subprocess.check_output(['docker', 'inspect', '--format',
        '{{json .Config.Labels}}', command[4]], text=True))
    if (labels.get('com.docker.compose.project') != args.namespace
            or labels.get('com.docker.compose.service') != 'execution-broker'):
        raise ValueError('owned Compose controller required')
    result = json.loads(subprocess.check_output(command, text=True))
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__': main()
