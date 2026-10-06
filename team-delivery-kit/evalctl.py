"""Local, fixed-scope bootstrap. Never prints secrets or starts an agent daemon."""
import argparse
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import urllib.request

ROOT = Path(__file__).resolve().parent
PRIVATE = Path(os.environ.get('DELIVERY_KIT_INSTANCE_HOME', str(ROOT / '.local')))
ENV_FILE = PRIVATE / 'evaluation.env'
PROJECT = os.environ.get('DELIVERY_KIT_COMPOSE_PROJECT', 'delivery-kit-eval')
BACKEND_PORT = os.environ.get('EVAL_BACKEND_PORT', '19080')
FRONTEND_PORT = os.environ.get('EVAL_FRONTEND_PORT', '19300')
if not re.fullmatch(r'delivery-kit-[a-z0-9-]{1,48}', PROJECT):
    raise ValueError('invalid evaluation Compose project')
if any(not value.isdigit() or not 1024 <= int(value) <= 65535
       for value in (BACKEND_PORT, FRONTEND_PORT)) or BACKEND_PORT == FRONTEND_PORT:
    raise ValueError('invalid evaluation localhost ports')
SERVICES = {'postgres', 'backend', 'frontend'}
OPTIONAL_COMPONENTS = {'runtime': 'runtime', 'execution-broker': 'execution-broker',
                       'model-proxy': 'model-proxy'}


def process_env():
    # Compose variables must come from the private env file, not unrelated shell keys.
    allowed = {'PATH', 'HOME', 'TMPDIR', 'DOCKER_HOST', 'DOCKER_CONTEXT', 'DOCKER_CONFIG',
               'DOCKER_TLS_VERIFY', 'DOCKER_CERT_PATH', 'XDG_RUNTIME_DIR',
               'EVAL_BACKEND_PORT', 'EVAL_FRONTEND_PORT', 'DELIVERY_KIT_COMPOSE_PROJECT'}
    return {k: v for k, v in os.environ.items() if k in allowed}


def initialize():
    if PRIVATE.is_symlink() or ENV_FILE.is_symlink():
        raise ValueError('private storage must not be a symlink')
    PRIVATE.mkdir(mode=0o700, exist_ok=True)
    PRIVATE.chmod(0o700)
    if ENV_FILE.exists():
        check_private()
        print('Existing private environment preserved.')
        return
    descriptor = os.open(ENV_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, 'w') as stream:
        stream.write(f'EVAL_DB_PASSWORD={secrets.token_hex(32)}\n')
        stream.write(f'EVAL_JWT_SECRET={secrets.token_hex(48)}\n')
    print('Private environment created (0600). No credentials displayed.')


def check_private():
    if PRIVATE.is_symlink() or ENV_FILE.is_symlink() or not ENV_FILE.is_file():
        raise ValueError('run init; private environment must be a regular file')
    if ENV_FILE.stat().st_mode & 0o077:
        raise ValueError('private environment permissions must be 0600')


def compose(args, capture=False):
    check_private()
    return subprocess.run(
        ['docker', 'compose', '--project-name', PROJECT, '--project-directory', str(ROOT),
         '--env-file', str(ENV_FILE), '-f', str(ROOT / 'compose.eval.yaml'), *args],
        env=process_env(), check=True, text=True, capture_output=capture,
    ).stdout


def verify():
    ids = compose(['ps', '--all', '-q', *sorted(SERVICES)], capture=True).split()
    if len(ids) != 3:
        raise ValueError('expected exactly three evaluation services')
    containers = json.loads(subprocess.check_output(['docker', 'inspect', *ids], env=process_env()))
    errors, summary, seen = [], [], set()
    for container in containers:
        labels = container['Config'].get('Labels') or {}
        service = labels.get('com.docker.compose.service')
        seen.add(service)
        if labels.get('com.docker.compose.project') != PROJECT or service not in SERVICES:
            errors.append('unexpected service ownership')
        if container['HostConfig'].get('Privileged'):
            errors.append(f'{service}: privileged')
        for mount in container.get('Mounts', []):
            if mount['Type'] != 'volume' or not mount.get('Name', '').startswith(PROJECT + '_'):
                errors.append(f'{service}: unexpected mount')
        if container['State']['Status'] != 'running':
            errors.append(f'{service}: not running')
        bindings = container['HostConfig'].get('PortBindings') or {}
        expected = {'backend': {'8080/tcp': BACKEND_PORT}, 'frontend': {'3000/tcp': FRONTEND_PORT}}.get(service, {})
        actual = {}
        for port, targets in bindings.items():
            for target in targets or []:
                if target.get('HostIp') != '127.0.0.1':
                    errors.append(f'{service}: non-loopback publication')
                actual[port] = target.get('HostPort')
        if actual != expected:
            errors.append(f'{service}: unexpected ports')
        values = dict(item.split('=', 1) for item in container['Config'].get('Env', []) if '=' in item)
        if any(values.get(key) for key in (
            'MULTICA_LLM_API_KEY', 'OPENROUTER_API_KEY', 'OPENAI_API_KEY',
            'GITHUB_TOKEN', 'GH_TOKEN', 'TELEGRAM_BOT_TOKEN',
        )):
            errors.append(f'{service}: unexpected external credentials')
        if service == 'backend' and any(values.get(key) != 'true' for key in ('DO_NOT_TRACK', 'ANALYTICS_DISABLED')):
            errors.append('backend: telemetry not disabled')
        summary.append({'service': service, 'state': container['State']['Status'],
                        'image': container['Config']['Image'], 'ports': actual})
    if seen != SERVICES:
        errors.append('missing evaluation service')
    for name, url in [('backend', 'http://127.0.0.1:' + BACKEND_PORT + '/health'),
                      ('frontend', 'http://127.0.0.1:' + FRONTEND_PORT + '/')]:
        try:
            with urllib.request.urlopen(url, timeout=10) as response:
                if response.status != 200:
                    errors.append(f'{name}: HTTP health failed')
        except Exception as error:
            errors.append(f'{name}: {type(error).__name__}')
    print(json.dumps({'control_plane_ok': not errors, 'services': summary, 'errors': errors,
                      'scope': 'control_plane_only',
                      'agent_runtime_assessed': False, 'autonomy_qualified': False}, indent=2))
    return bool(errors)


def component_status():
    """Report optional execution components without exposing their environment."""
    result = {}
    for service, label in OPTIONAL_COMPONENTS.items():
        name = f'{PROJECT}-{service}-1'
        process = subprocess.run(['docker', 'inspect', name], env=process_env(),
                                 text=True, capture_output=True)
        if process.returncode:
            result[service] = {'state': 'missing'}
            continue
        try:
            containers = json.loads(process.stdout)
            container = containers[0]
            labels = container['Config'].get('Labels') or {}
            if labels.get('com.docker.compose.project') != PROJECT or labels.get('com.docker.compose.service') != label:
                result[service] = {'state': 'identity_mismatch'}
                continue
            violations = []
            if service in ('runtime', 'model-proxy'):
                environment_names = {entry.split('=', 1)[0] for entry in container['Config'].get('Env', [])}
                disallowed = {'GITHUB_TOKEN', 'GH_TOKEN', 'TELEGRAM_BOT_TOKEN',
                              'OPENROUTER_API_KEY', 'OPENAI_API_KEY'}
                if environment_names.intersection(disallowed):
                    violations.append('unexpected_credential_environment')
                if any(mount.get('Destination') == '/var/run/docker.sock' for mount in container.get('Mounts', [])):
                    violations.append('unexpected_docker_socket')
            result[service] = {
                'state': container['State']['Status'],
                'exit_code': container['State']['ExitCode'],
                'restart_policy': container['HostConfig']['RestartPolicy']['Name'],
                'violations': violations,
            }
        except (ValueError, IndexError, KeyError, TypeError):
            result[service] = {'state': 'unreadable'}
    return result


def status():
    # The base Compose `ps` omits the optional runtime and broker. Keep them visible.
    compose(['ps'])
    components = component_status()
    print(json.dumps({'execution_components': components,
                      'native_bounded_text_prompts_enabled': True,
                      'delivery_qualified': False}, indent=2))
    return 0 if all(item['state'] == 'running' and not item.get('violations')
                    for item in components.values()) else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['init', 'up', 'stop', 'restart', 'status', 'verify'])
    action = parser.parse_args().action
    if action == 'init':
        initialize()
    elif action == 'verify':
        return verify()
    elif action == 'status':
        return status()
    else:
        arguments = {'up': ['up', '-d'], 'stop': ['stop'], 'restart': ['restart']}
        compose(arguments[action])
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
