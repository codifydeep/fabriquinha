"""Seed only isolated runtime state; never copy a user's Hermes home or provider keys."""
import json
import subprocess

from bootstrap_multica import AUTH, PRIVATE
from evalctl import process_env, ROOT, ENV_FILE, PROJECT, FRONTEND_PORT


def main():
    account = json.loads(AUTH.read_text())
    workspace = json.loads((PRIVATE / 'workspace.json').read_text())
    config = {
        'server_url': 'http://backend:8080', 'app_url': 'http://localhost:' + FRONTEND_PORT,
        'workspace_id': workspace['id'], 'token': account['token'],
        'device_name': PROJECT, 'runtime_name': 'Hermes isolated evaluation ' + PROJECT,
        'workspaces_root': '/eval-state/workspaces', 'max_concurrent_tasks': 2,
        'disable_auto_update': True, 'disable_auto_reload': True,
    }
    # The receiver is fixed installation code, not an agent-supplied command.
    receiver = '''
import json, os, pathlib, sys
value = json.load(sys.stdin)
path = pathlib.Path('/eval-state/.multica/config.json')
path.parent.mkdir(mode=0o700, exist_ok=True)
if path.exists():
    if json.loads(path.read_text()) != value:
        raise SystemExit('existing runtime configuration differs; refusing overwrite')
else:
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(value, stream)
print('isolated runtime configuration ready; no provider credentials')
'''
    subprocess.run(['docker', 'compose', '--project-name', PROJECT, '--project-directory', str(ROOT),
                    '--env-file', str(ENV_FILE), '-f', str(ROOT / 'compose.eval.yaml'),
                    '-f', str(ROOT / 'compose.runtime.yaml'), '--profile', 'runtime',
                    'run', '--rm', '-T', '--no-deps', '--entrypoint', 'python', 'runtime', '-c', receiver],
                   input=json.dumps(config), text=True, env=process_env(), check=True)


if __name__ == '__main__':
    main()
