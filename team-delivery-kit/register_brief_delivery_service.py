"""Install one credential-free native service for an operator-selected brief.

Registration does not start tasks. launchctl bootstrap is a separate host action.
The pipeline hashes all inputs; blocked outcomes do not spin KeepAlive.
"""
import argparse
import os
from pathlib import Path
import plistlib
import sys

from planned_delivery import load_configuration


def write_once(path, content):
    if path.is_symlink():
        raise ValueError('unsafe service artifact')
    if path.exists():
        if path.read_bytes() != content:
            raise ValueError('service registration drift')
        return
    with path.open('xb') as stream:
        stream.write(content)
    path.chmod(0o600)


def main():
    import json
    from evalctl import PRIVATE, PROJECT, BACKEND_PORT, FRONTEND_PORT
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    parser.add_argument('--persist-login', action='store_true')
    args = parser.parse_args()
    if sys.platform != 'darwin' or PROJECT != 'delivery-kit-port2' or BACKEND_PORT != '19081':
        raise ValueError('native brief registration restricted to macOS port2')
    config = load_configuration(args.config)
    root = Path(__file__).resolve().parent
    service = 'com.codifydeep.delivery-kit.port2.brief-' + config['name'].lower()
    directory = PRIVATE / 'host-service'
    if directory.is_symlink():
        raise ValueError('unsafe service directory')
    directory.mkdir(mode=0o700, exist_ok=True)
    log_directory = Path.home() / 'Library' / 'Logs' / 'DeliveryKit' / PROJECT
    if any(p.is_symlink() for p in (log_directory, *log_directory.parents)):
        raise ValueError('unsafe native service log directory')
    log_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    log = log_directory / (config['name'] + '.log')
    if log.is_symlink():
        raise ValueError('unsafe native service log')
    log.touch(mode=0o600, exist_ok=True)
    log.chmod(0o600)
    env = {'PATH': '/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin',
           'DELIVERY_KIT_INSTANCE_HOME': str(PRIVATE), 'DELIVERY_KIT_COMPOSE_PROJECT': PROJECT,
           'EVAL_BACKEND_PORT': BACKEND_PORT, 'EVAL_FRONTEND_PORT': FRONTEND_PORT,
           'DELIVERY_KIT_BRIEF_DELIVERY_CONFIG': str(config['path']),
           'DELIVERY_KIT_BRIEF_SERVICE': '1'}
    plist = {'Label': service, 'ProgramArguments': [sys.executable, '-u',
              str(root / 'brief_delivery_supervisor.py')], 'WorkingDirectory': str(Path.home()),
             'EnvironmentVariables': env, 'RunAtLoad': True, 'StartInterval': 60,
             'KeepAlive': {'SuccessfulExit': False}, 'ThrottleInterval': 60,
             'StandardOutPath': str(log), 'StandardErrorPath': str(log)}
    target = directory / (service + '.native.plist')
    write_once(target, plistlib.dumps(plist, sort_keys=True))
    login = None
    if args.persist_login:
        folder = Path.home() / 'Library' / 'LaunchAgents'
        if any(p.is_symlink() for p in (folder, *folder.parents)):
            raise ValueError('unsafe login service directory')
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        login = folder / (service + '.plist')
        write_once(login, target.read_bytes())
    write_once(directory / (config['name'] + '.brief-input.json'),
               (json.dumps({'input_sha256': config['sha256'], 'configuration': str(config['path'])},
                           sort_keys=True, indent=2) + '\n').encode())
    print(json.dumps({'service': service, 'plist': str(target),
                      'login_plist': str(login) if login else None, 'installed': False,
                      'input_sha256': config['sha256']}))


if __name__ == '__main__':
    main()
