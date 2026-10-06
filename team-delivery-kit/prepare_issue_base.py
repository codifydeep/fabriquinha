"""Operator-only GitHub main -> immutable Docker base for one Multica issue."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import uuid
from docker_grouping import args as docker_group_args

from project_selection import current
from evalctl import PROJECT as INSTANCE_PROJECT
from portable_contract import is_test_path, load as load_portable_contract
from test_runner_policy import workspace_command
from controller_broker_image import installed_image

ROOT = Path(__file__).parent
PROJECT = current()
REPO = PROJECT['checkout']
FILES = ('AGENTS.md', 'calc.py', 'test_calc.py')
OWNER = INSTANCE_PROJECT + '-broker-v1'


def command(*args, cwd=ROOT):
    return subprocess.check_output(args, cwd=cwd, text=True).strip()


def broker_post(path, payload):
    if path not in ('/v1/issue-bases', '/v1/issue-requirements', '/v1/issue-editables',
                    '/v1/snapshots', '/v1/review-assignments', '/v1/delivery-routes', '/v1/delivery-status',
                    '/v1/candidate-corrections', '/v1/candidate-qualification', '/v1/candidate-semantic-experiment', '/v1/candidate-semantic-revalidation', '/v1/candidate-repair-findings', '/v1/reconcile-failed-suite', '/v1/failed-execution-diagnosis', '/v1/failed-execution-evidence', '/v1/challenge-suite-diagnosis', '/v1/test-revision-trials',
                    '/v1/test-review-bootstrap-recovery', '/v1/test-review-inspection-recovery',
                    '/v1/test-review-pagination-recovery', '/v1/test-review-acp-recovery', '/v1/test-review-size-recovery', '/v1/test-review-storage-recovery', '/v1/test-review-evidence-challenge',
                    '/v1/review-policy-revalidation', '/v1/test-review-semantic-revalidation', '/v1/assertion-replan', '/v1/test-first-diagnostic-recovery', '/v1/test-first-bootstrap-recovery', '/v1/test-first-format-recovery', '/v1/test-first-artifact-recovery',
                    '/v1/qa-diagnostic-artifacts', '/v1/execution-stall-recovery'):
        raise ValueError('unsupported operator registration')
    subprocess.run(['docker', 'exec', '-i', INSTANCE_PROJECT + '-execution-broker-1',
                    'python', '-c',
                    'import json,urllib.request,sys; from pathlib import Path; '
                    'p=json.load(sys.stdin); '
                    'r=urllib.request.Request("http://127.0.0.1:8090"+sys.argv[1], '
                    'data=json.dumps(p).encode(),headers={"Authorization":"Bearer "+Path("/broker-state/token").read_text(),"Content-Type":"application/json"}); '
                    'print(urllib.request.urlopen(r).read().decode())', path],
                   input=json.dumps(payload), text=True, check=True)


def verified_main():
    remote = command('git', 'remote', 'get-url', 'origin', cwd=REPO)
    if remote not in (PROJECT['remote_https'], PROJECT['remote_ssh']):
        raise ValueError('unexpected Git remote')
    sha = command('gh', 'api', 'repos/' + PROJECT['repository'] + '/git/ref/heads/main',
                  '--jq', '.object.sha')
    if not re.fullmatch(r'[0-9a-f]{40}', sha):
        raise ValueError('invalid remote main SHA')
    if command('git', 'rev-parse', 'HEAD', cwd=REPO) != sha:
        raise ValueError('local checkout is not remote main')
    checks = json.loads(command('gh', 'api', f'repos/{PROJECT["repository"]}/commits/{sha}/check-runs'))
    if not any(run.get('name') == 'ci' and run.get('conclusion') == 'success'
               for run in checks.get('check_runs', [])):
        raise ValueError('main CI is not green')
    return sha


def prepare(issue_id):
    if str(uuid.UUID(issue_id)) != issue_id:
        raise ValueError('canonical issue UUID required')
    sha = verified_main()
    image = installed_image(INSTANCE_PROJECT)
    volume = INSTANCE_PROJECT + '-base-' + issue_id
    labels = {'delivery-kit.owner': OWNER, 'delivery-kit.issue-id': issue_id,
              'delivery-kit.base-sha': sha}
    with tempfile.TemporaryDirectory(prefix='delivery-kit-base-') as directory:
        folder = Path(directory)
        files = {}
        contract_path = os.environ.get('DELIVERY_KIT_DELIVERY_CONTRACT')
        contract = load_portable_contract(contract_path) if contract_path else None
        if contract and contract['repository'] != PROJECT['repository']:
            raise ValueError('portable contract repository mismatch')
        if contract:
            tracked = command('git', 'ls-tree', '-r', '--name-only', sha, cwd=REPO).splitlines()
            baseline_tests = {name for name in tracked if any(
                is_test_path(name, root, contract['test_command'][0])
                for root in contract['test_roots'])}
            if not baseline_tests <= set(contract['protected_files']):
                raise ValueError('portable base omits protected baseline tests')
        names = FILES if contract is None else tuple(
            name for name in contract['files'] if name not in contract['editable_files']
            or subprocess.run(['git', 'cat-file', '-e', f'{sha}:{name}'], cwd=REPO,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0)
        for name in names:
            data = subprocess.check_output(['git', 'show', f'{sha}:{name}'], cwd=REPO)
            if len(data) > 32768:
                raise ValueError('base file too large')
            (folder / name).parent.mkdir(parents=True, exist_ok=True)
            (folder / name).write_bytes(data)
            files[name] = hashlib.sha256(data).hexdigest()
        if contract is not None:
            encoded = json.dumps(contract, sort_keys=True, separators=(',', ':')).encode()
            (folder / 'contract.json').write_bytes(encoded)
            files['contract.json'] = hashlib.sha256(encoded).hexdigest()
        manifest = json.dumps({'base_sha': sha, 'files': files}, sort_keys=True,
                              separators=(',', ':')).encode()
        (folder / 'manifest.json').write_bytes(manifest)
        digest = hashlib.sha256(manifest).hexdigest()
        inspect = subprocess.run(['docker', 'volume', 'inspect', volume], capture_output=True, text=True)
        if inspect.returncode == 0:
            existing = json.loads(inspect.stdout)[0]
            if any(existing.get('Labels', {}).get(k) != v for k, v in labels.items()):
                raise ValueError('existing base volume identity mismatch')
        else:
            subprocess.run(['docker', 'volume', 'create',
                            *(f'--label={k}={v}' for k, v in labels.items()), volume], check=True,
                           stdout=subprocess.DEVNULL)
        # No Docker socket, network, or Git credentials in this one-shot writer.
        subprocess.run(['docker', 'run', '--rm', '--network', 'none', '--read-only',
                        *docker_group_args('base-copy'),
                        '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
                        '--mount', f'type=bind,source={folder},target=/source,readonly',
                        '--mount', f'type=volume,source={volume},target=/target,volume-nocopy',
                        '--entrypoint', 'python', image, '/base_copy.py'], check=True)
    payload = {'issue_id': issue_id, 'base_sha': sha, 'volume': volume,
               'manifest_sha256': digest}
    # Controller token never appears in argv or Telegram. Execute the request
    # inside the broker namespace from its private state file.
    broker_post('/v1/issue-bases', payload)
    if contract is not None:
        broker_post('/v1/issue-editables', {'issue_id': issue_id,
            'paths': ['/workspace/' + name for name in contract['editable_files']],
            'test_command': workspace_command(contract['test_command'],
                                              contract['test_roots'])})
    return payload


if __name__ == '__main__':
    import sys
    print(json.dumps(prepare(sys.argv[1])))
