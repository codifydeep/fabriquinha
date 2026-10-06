"""Operator-run, exact-SHA Docker deployment probe for the public sandbox.

This is not an autonomous release controller. It never accepts a worker-supplied
SHA or repository URL, and it does not mount the Docker socket into the app.
"""
import json
import argparse
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from project_selection import current
from docker_grouping import args as docker_group_args


ROOT = Path(__file__).resolve().parent
PROJECT = current()
REPO = PROJECT['checkout']
REMOTE = PROJECT['remote_https']
SLOTS = {1: ('delivery-kit-eval-calculator', 19301),
         2: ('delivery-kit-eval-calculator-eval10', 19302),
         3: ('delivery-kit-eval-calculator-eval10-qa', 19303),
         4: ('delivery-kit-eval-calculator-eval14-qa', 19304),
         5: ('delivery-kit-eval-calculator-eval15-qa', 19305),
         6: ('delivery-kit-eval-calculator-eval16-qa', 19306),
         7: ('delivery-kit-eval-calculator-eval18-qa', 19307),
         8: ('delivery-kit-eval-calculator-port1-qa', 19308),
         9: ('delivery-kit-port2-calculator-port2-qa', 19311)}
CONTAINER, PORT = SLOTS[1]


def command(*args):
    return subprocess.check_output(args, text=True).strip()


def json_command(*args):
    return json.loads(command(*args))


def trusted_source():
    if command('git', '-C', str(REPO), 'remote', 'get-url', 'origin') != REMOTE:
        raise ValueError('sandbox remote changed')
    if command('git', '-C', str(REPO), 'branch', '--show-current') != 'main':
        raise ValueError('sandbox checkout must be main')
    if command('git', '-C', str(REPO), 'status', '--porcelain', '--untracked-files=no'):
        raise ValueError('tracked checkout is dirty')
    sha = command('git', '-C', str(REPO), 'rev-parse', 'HEAD')
    remote = json_command('gh', 'api', 'repos/' + PROJECT['repository'] + '/git/ref/heads/main')
    if remote['object']['sha'] != sha:
        raise ValueError('checkout does not match GitHub main')
    runs = json_command('gh', 'api', 'repos/' + PROJECT['repository'] + '/actions/runs?head_sha=' + sha)
    matches = [r for r in runs.get('workflow_runs', [])
               if r.get('head_sha') == sha and r.get('event') == 'push'
               and r.get('path') == '.github/workflows/ci.yml'
               and r.get('conclusion') == 'success']
    if not matches:
        raise ValueError('successful automatic CI missing on exact main SHA')
    return sha, matches[0]['html_url']


def get_json(path):
    with urllib.request.urlopen('http://127.0.0.1:' + str(PORT) + path, timeout=2) as response:
        return response.status, json.load(response)


def qa_cases(slot):
    cases = [('/multiply?left=7&right=3', 21),
             ('/multiply?left=-7&right=3', -21),
             ('/multiply?left=5&right=0', 0)]
    if slot == 8:
        return cases + [('/cube?value=-2', -8), ('/cube?value=3', 27)]
    if slot == 9:
        return cases + [('/cube?value=-2', -8), ('/cube?value=3', 27),
                        ('/negate?value=-2', 2), ('/negate?value=3', -3)]
    cases.extend([('/square?value=-3', 9), ('/square?value=4', 16)])
    if slot >= 4:
        cases.extend([('/cube?value=-2', -8), ('/cube?value=3', 27)])
    if slot == 5:
        cases.extend([('/negate?value=-2', 2), ('/negate?value=3', -3)])
    if slot >= 6:
        cases.extend([('/negate?value=-2', 2), ('/negate?value=3', -3),
                      ('/absolute?value=-2', 2), ('/absolute?value=3', 3)])
    if slot == 7:
        cases.extend([('/double?value=-2', -4), ('/double?value=3', 6)])
    return cases


def verify_existing(slot, sha):
    global CONTAINER, PORT
    CONTAINER, PORT = SLOTS[slot]
    details = json_command('docker', 'inspect', CONTAINER)
    if len(details) != 1:
        raise ValueError('deployment identity missing')
    container = details[0]
    if not container['State']['Running'] or container['HostConfig'].get('Privileged'):
        raise ValueError('deployment not safely running')
    bindings = container['HostConfig'].get('PortBindings') or {}
    if bindings.get('8080/tcp') != [{'HostIp': '127.0.0.1', 'HostPort': str(PORT)}]:
        raise ValueError('deployment port binding mismatch')
    image = json_command('docker', 'image', 'inspect', container['Image'])
    if len(image) != 1 or image[0]['Config']['Labels'].get('delivery-kit.source-sha') != sha:
        raise ValueError('deployment image SHA mismatch')
    if get_json('/health') != (200, {'status': 'ok', 'source_sha': sha}):
        raise ValueError('deployment health mismatch')
    cases = qa_cases(slot)
    for path, expected in cases:
        if get_json(path) != (200, {'result': expected, 'source_sha': sha}):
            raise ValueError('post-deploy QA failed: ' + path)
    return {'source_sha': sha, 'image_id': image[0]['Id'], 'container': CONTAINER,
            'url': 'http://127.0.0.1:' + str(PORT), 'post_deploy_qa_cases': len(cases),
            'feature_qa': 'double' if slot == 7 else 'absolute' if slot == 6 else 'negate' if slot in (5, 9) else 'cube' if slot in (4, 8) else 'square',
            'qa_status': 'passed'}


def main(slot=1):
    global CONTAINER, PORT
    CONTAINER, PORT = SLOTS[slot]
    sha, ci_url = trusted_source()
    existing = subprocess.run(['docker', 'container', 'inspect', CONTAINER],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if existing.returncode == 0:
        raise ValueError('evaluation deployment container already exists; inspect it first')
    tag = 'delivery-kit-eval-calculator:' + sha[:12]
    with tempfile.TemporaryDirectory(prefix='delivery-kit-eval-build-') as scratch:
        context = Path(scratch)
        for filename in ('calc.py', 'test_calc.py'):
            content = subprocess.check_output(['git', '-C', str(REPO), 'show', sha + ':' + filename])
            (context / filename).write_bytes(content)
        shutil.copyfile(ROOT / 'deploy' / 'serve_calc.py', context / 'serve_calc.py')
        shutil.copyfile(ROOT / 'deploy' / 'Dockerfile.eval-service', context / 'Dockerfile')
        subprocess.run(['docker', 'build', '--pull=false', '--build-arg', 'SOURCE_SHA=' + sha,
                        '-t', tag, str(context)], check=True, stdout=subprocess.DEVNULL)
    image = json_command('docker', 'image', 'inspect', tag)
    if len(image) != 1 or image[0]['Config']['Labels'].get('delivery-kit.source-sha') != sha:
        raise ValueError('built image identity mismatch')
    subprocess.run(['docker', 'run', '-d', '--name', CONTAINER, '--network', 'bridge',
                    *docker_group_args('app', kind='homologation'),
                    '--publish', '127.0.0.1:' + str(PORT) + ':8080', '--read-only',
                    '--tmpfs', '/tmp:rw,nosuid,nodev,size=8m', '--cap-drop', 'ALL',
                    '--security-opt', 'no-new-privileges', '--memory', '128m',
                    '--cpus', '0.5', '--pids-limit', '64', '--restart', 'no', tag],
                   check=True, stdout=subprocess.DEVNULL)
    try:
        for _ in range(20):
            try:
                health = get_json('/health')
                break
            except (OSError, urllib.error.URLError):
                time.sleep(1)
        else:
            raise TimeoutError('local deployment failed health check')
        if health != (200, {'status': 'ok', 'source_sha': sha}):
            raise ValueError('deployed SHA or health mismatch')
        cases = qa_cases(slot)
        for path, expected in cases:
            if get_json(path) != (200, {'result': expected, 'source_sha': sha}):
                raise ValueError('post-deploy QA failed: ' + path)
    except Exception:
        subprocess.run(['docker', 'stop', CONTAINER], check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        raise
    print(json.dumps({'source_sha': sha, 'ci_run': ci_url, 'image_id': image[0]['Id'],
                      'container': CONTAINER, 'url': 'http://127.0.0.1:' + str(PORT),
                      'post_deploy_qa_cases': len(cases),
                      'feature_qa': 'double' if slot == 7 else 'absolute' if slot == 6 else 'negate' if slot in (5, 9) else 'cube' if slot in (4, 8) else 'square',
                      'qa_status': 'passed'}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--slot', type=int, choices=sorted(SLOTS), default=1)
    main(parser.parse_args().slot)
