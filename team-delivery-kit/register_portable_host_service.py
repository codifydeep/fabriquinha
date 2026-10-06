"""Generate a pinned, credential-free user launchd registration in the workspace.

Does not bootstrap launchd, create issues or execute agents. Installation is an
explicit host operation using the generated plist; no global service edits.
"""
import argparse
import hashlib
import json
from pathlib import Path
import plistlib
import re
import sys

from portable_host_service import load_config, read_object


def main():
    parser = argparse.ArgumentParser()
    for name in ('private', 'project', 'contract', 'run', 'instance', 'backend-port', 'frontend-port'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--persist-login', action='store_true')
    parser.add_argument('--native-paths', action='store_true', default=sys.platform == 'darwin')
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    private = Path(args.private)
    project, contract, spec = [Path(value).resolve() for value in (args.project, args.contract, args.run)]
    label = read_object(spec)['label']
    if not re.fullmatch(r'[A-Z][A-Z0-9]{1,31}-[1-9][0-9]{0,5}', label):
        raise ValueError('invalid service label')
    context = read_object(private / ('portable-context-' + label + '.json'))
    env = dict(DELIVERY_KIT_INSTANCE_HOME=str(private), DELIVERY_KIT_PROJECT_CONFIG=str(project),
        DELIVERY_KIT_DELIVERY_CONTRACT=str(contract), DELIVERY_KIT_RUN_SPEC=str(spec),
        DELIVERY_KIT_COMPOSE_PROJECT=args.instance, EVAL_BACKEND_PORT=args.backend_port,
        EVAL_FRONTEND_PORT=args.frontend_port, DELIVERY_KIT_TEST_FIRST='1')
    config = dict(schema=1, label=label, issue_id=context['issue_id'], environment=env,
        inputs={str(path):hashlib.sha256(path.read_bytes()).hexdigest() for path in (project,contract,spec)})
    directory = private / 'host-service'
    if directory.is_symlink():
        raise ValueError('unsafe registration directory')
    directory.mkdir(mode=0o700, exist_ok=True)
    path = directory / (label + '.config.json')
    encoded = (json.dumps(config,sort_keys=True,indent=2) + '\n').encode()
    pin = hashlib.sha256(encoded).hexdigest()
    def write_once(target, content):
        if target.is_symlink():
            raise ValueError('unsafe registration path')
        if target.exists():
            if target.read_bytes() != content:
                raise ValueError('registration replacement requires explicit retirement')
        else:
            with target.open('xb') as out:
                out.write(content)
            target.chmod(0o600)
    write_once(path, encoded)
    load_config(path, pin)
    service = 'com.codifydeep.delivery-kit.' + args.instance.removeprefix('delivery-kit-') + '.' + label.lower()
    if not re.fullmatch(r'[a-z0-9.-]+',service):
        raise ValueError('invalid launchd label')
    log_folder = directory
    if args.native_paths:
        log_folder = Path.home() / 'Library' / 'Logs' / 'DeliveryKit' / args.instance
        if any(p.is_symlink() for p in (log_folder, *log_folder.parents)):
            raise ValueError('unsafe native log directory')
        log_folder.mkdir(mode=0o700,parents=True,exist_ok=True)
    log = log_folder / (label + '.log')
    if log.is_symlink():
        raise ValueError('unsafe service log')
    log.touch(mode=0o600,exist_ok=True);log.chmod(0o600)
    plist = dict(Label=service, ProgramArguments=[sys.executable, '-u', str(root/'portable_host_service.py'),
        '--config',str(path),'--pin',pin], WorkingDirectory=str(Path.home() if args.native_paths else root),
        EnvironmentVariables={'PATH':'/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin'},
        RunAtLoad=True, StartInterval=60, KeepAlive={'SuccessfulExit':False},
        ThrottleInterval=60, StandardOutPath=str(log), StandardErrorPath=str(log))
    target = directory / (service + ('.native.plist' if args.native_paths else '.plist'))
    write_once(target, plistlib.dumps(plist,sort_keys=True))
    login_path = None
    if args.persist_login:
        if sys.platform != 'darwin':
            raise ValueError('login registration requires macOS')
        login_folder = Path.home() / 'Library' / 'LaunchAgents'
        if any(p.is_symlink() for p in (login_folder, *login_folder.parents)):
            raise ValueError('unsafe login service directory')
        login_folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        login_path = login_folder / (service + '.plist')
        write_once(login_path, target.read_bytes())
    print(json.dumps(dict(plist=str(target), service=service, config_pin=pin,
                         issue_id=config['issue_id'], installed=False,
                         login_plist=str(login_path) if login_path else None)))


if __name__ == '__main__':
    main()
