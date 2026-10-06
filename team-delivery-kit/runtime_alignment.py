"""Offline, immutable-image runtime alignment gate for the stdlib pilot."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
from docker_grouping import args as docker_group_args

from bootstrap_multica import PRIVATE
from release_eval import save_receipt


ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / 'projects' / 'pilot-feedback-board.runtime.json'
IMAGE = re.compile(r'(?:sha256:|[a-z0-9./_-]+@sha256:)[0-9a-f]{64}\Z')
PROBE = ('import json,sqlite3,sys; print(json.dumps({"python":list(sys.version_info[:3]),'
         '"sqlite":sqlite3.sqlite_version}))')


def probe(image):
    if not isinstance(image, str) or not IMAGE.fullmatch(image):
        raise ValueError('runtime image must be immutable')
    result = subprocess.check_output([
        'docker', 'run', '--rm', '--network', 'none', '--read-only',
        *docker_group_args('runtime-probe'),
        '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
        '--entrypoint', 'python', image, '-c', PROBE], text=True, timeout=30)
    value = json.loads(result)
    if (not isinstance(value, dict) or set(value) != {'python', 'sqlite'}
            or not isinstance(value['python'], list) or len(value['python']) != 3
            or any(type(part) is not int for part in value['python'])
            or not isinstance(value['sqlite'], str)):
        raise ValueError('invalid runtime probe receipt')
    return value


def compare(worker, test, deployment):
    if deployment is None:
        return 'blocked_deployment_image_missing'
    return 'aligned' if worker == test == deployment else 'blocked_runtime_mismatch'


def main():
    content = CONFIG.read_bytes()
    config = json.loads(content)
    if set(config) != {'worker_image', 'test_image', 'deployment_image'}:
        raise ValueError('invalid runtime config')
    receipts = {role: probe(config[role + '_image']) for role in ('worker', 'test')}
    if config['deployment_image'] is not None:
        receipts['deployment'] = probe(config['deployment_image'])
    stage = compare(receipts['worker'], receipts['test'], receipts.get('deployment'))
    if receipts['worker'] != receipts['test']:
        stage = 'blocked_runtime_mismatch'
    result = {'config_sha256': hashlib.sha256(content).hexdigest(),
              'stage': stage, 'runtimes': receipts,
              'next_action': 'CTO must resolve exact worker/test/deploy runtime contract' if stage != 'aligned' else None}
    save_receipt(PRIVATE / 'runtime-alignment' / 'PILOT-FEEDBACK-BOARD.json', result)
    print(json.dumps(result, sort_keys=True))
    return 0 if stage == 'aligned' else 1


if __name__ == '__main__':
    raise SystemExit(main())
