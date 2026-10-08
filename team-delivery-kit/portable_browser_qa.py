"""Fixed, model-free browser QA on a fresh copy of the exact deployed image.

No live database writes, arbitrary agent commands, host network, secrets or socket
mounts. Intent precedes side effects; failed/interrupted attempts require explicit
diagnosis rather than identical automatic retries.
"""
import base64
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time
import uuid
from docker_grouping import args as docker_group_args

from release_eval import save_receipt
from browser_qa_recipes import SCENARIOS, recipe_for, baseline_for
import browser_qa_composition as composition

SCRIPT = Path(__file__).with_name('browser_feedback_acceptance.py')
SHA = re.compile(r'[a-f0-9]{40}\Z')
IMAGE = re.compile(r'sha256:[a-f0-9]{64}\Z')


def validate(config):
    if (not isinstance(config, dict) or set(config) != {'scenario', 'browser_image'}
            or config['scenario'] not in SCENARIOS
            or not isinstance(config['browser_image'], str)
            or not IMAGE.fullmatch(config['browser_image'])):
        raise ValueError('invalid pinned browser QA configuration')
    return config


def script_for(config):
    validate(config)
    recipe = recipe_for(config['scenario'])
    return SCRIPT if recipe.name == 'browser_feedback_acceptance.py' else recipe


def _resolution_evidence(private, incident, failed_path, passed_path, *, require_current=True):
    if incident.get('phase') != 'browser' or not re.fullmatch(r'[a-f0-9]{16}', incident.get('key', '')):
        raise ValueError('exact browser incident required')
    folder = (Path(private) / 'browser-acceptance' / incident['label']).resolve()
    paths = [Path(failed_path), Path(passed_path)]
    for path in paths:
        if (path.is_symlink() or path.resolve().parent != folder or not path.is_file()
                or not re.fullmatch(r'[a-f0-9]{64}\.json', path.name)
                or path.stat().st_size > 65536):
            raise ValueError('unsafe browser resolution evidence')
    old, new = [json.loads(path.read_text()) for path in paths]
    old_id, new_id = old.get('identity', {}), new.get('identity', {})
    if (old.get('status') != 'failed' or old.get('cleanup') != 'passed'
            or new.get('status') != 'passed' or new.get('cleanup') != 'passed'
            or new.get('automated') is not True
            or new_id.get('source_sha') != incident['source_sha']
            or new.get('result', {}).get('source_sha') != incident['source_sha']
            or new.get('result', {}).get('status') != 'passed'
            or not old_id.get('scenario_sha256')
            or old_id.get('scenario_sha256') == new_id.get('scenario_sha256')
            or not re.fullmatch(r'[a-f0-9]{64}', new_id.get('scenario_sha256', ''))
            or (require_current and new_id.get('scenario_sha256') != hashlib.sha256(script_for(new_id['config']).read_bytes()).hexdigest())
            or {k:v for k,v in old_id.items() if k != 'scenario_sha256'} !=
               {k:v for k,v in new_id.items() if k != 'scenario_sha256'}):
        raise ValueError('scenario resolution requires unchanged product and new verified browser evidence')
    screenshot = paths[1].with_suffix('.png')
    if (screenshot.is_symlink() or not screenshot.is_file()
            or screenshot.stat().st_size > 10485760
            or hashlib.sha256(screenshot.read_bytes()).hexdigest() != new.get('screenshot_sha256')):
        raise ValueError('browser resolution screenshot drift')
    return {str(path.resolve()): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def register_scenario_resolution(private, incident, failed_path, passed_path, reason):
    """Operator-only repair of a QA scenario, never approval of changed product.

    Both immutable attempt receipts remain intact. Reconciliation still reruns
    deployment identity/CI/approval checks and the current browser gate.
    """
    if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 1000:
        raise ValueError('bounded scenario repair justification required')
    evidence = _resolution_evidence(private, incident, failed_path, passed_path)
    value = {'incident_key': incident['key'], 'parent_issue_id': incident['parent_issue_id'],
             'source_sha': incident['source_sha'], 'reason': reason,
             'failed_path': str(Path(failed_path).resolve()),
             'passed_path': str(Path(passed_path).resolve()), 'evidence': evidence,
             'stage': 'scenario_corrected_browser_passed_not_release_approved'}
    path = Path(private) / 'browser-scenario-resolutions' / (incident['key'] + '.json')
    if path.is_symlink():
        raise ValueError('unsafe scenario resolution path')
    if path.exists() and json.loads(path.read_text()) != value:
        raise ValueError('scenario resolution identity drift')
    if not path.exists():
        save_receipt(path, value)
    return value


def scenario_resolution(private, incident):
    if incident.get('phase') != 'browser':
        return None
    if not re.fullmatch(r'[a-f0-9]{16}', incident.get('key', '')):
        raise ValueError('invalid browser incident key')
    path = Path(private) / 'browser-scenario-resolutions' / (incident['key'] + '.json')
    if not path.exists():
        return None
    if path.is_symlink() or path.stat().st_size > 65536:
        raise ValueError('unsafe browser scenario resolution')
    value = json.loads(path.read_text())
    if (value.get('incident_key') != incident['key']
            or value.get('parent_issue_id') != incident['parent_issue_id']
            or value.get('source_sha') != incident['source_sha']
            or value.get('stage') != 'scenario_corrected_browser_passed_not_release_approved'
            or value.get('evidence') != _resolution_evidence(private, incident,
                                         value['failed_path'], value['passed_path'], require_current=False)):
        raise ValueError('browser scenario resolution evidence drift')
    return value


def docker(*args, check=True, timeout=30):
    return subprocess.run(['docker', *args], text=True, capture_output=True,
                          check=check, timeout=timeout)


def inspect(target, kind='container'):
    return json.loads(docker(kind, 'inspect', target).stdout)[0]


def cleanup(resources, owner):
    for kind, name in reversed(resources):
        probe = docker(kind, 'inspect', name, check=False)
        if probe.returncode:
            # Distinguish an absent resource from an unavailable Docker daemon.
            docker('info', '--format', '{{.ServerVersion}}')
            if 'No such' not in probe.stderr:
                raise ValueError('browser QA cleanup inspection failed')
            continue
        data = json.loads(probe.stdout)[0]
        labels = data.get('Labels', {}) if kind == 'network' else data['Config'].get('Labels', {})
        if labels.get('delivery-kit.browser-qa') != owner:
            raise ValueError('browser QA cleanup ownership mismatch')
        try:
            docker(kind, 'rm', *(['--force'] if kind == 'container' else []), data['Id'])
        except subprocess.TimeoutExpired:
            # A lost deletion acknowledgement is not permission to repeat it.
            # Confirm daemon health and exact resource absence instead.
            observed=docker(kind,'inspect',name,check=False)
            docker('info','--format','{{.ServerVersion}}')
            if (observed.returncode==0 or not ('No such' in observed.stderr or
                    (kind=='network' and 'network '+name+' not found' in observed.stderr))):
                raise ValueError('browser QA cleanup timeout; absence unproven')


def qualify(*, config, deployed_container, source_sha, evidence_dir, runtime_env):
    validate(config)
    parameters = dict(deployed_container=deployed_container, source_sha=source_sha,
                      evidence_dir=evidence_dir, runtime_env=runtime_env)
    baseline = baseline_for(config['scenario'])
    if not baseline:
        return _qualify_one(config=config, **parameters)
    baseline_config = {**config, 'scenario': baseline}
    baseline_receipt = _qualify_one(config=baseline_config, **parameters)
    proof = composition.reference(evidence_dir, baseline_receipt)
    return _qualify_one(config=config, baseline_proof=proof,
                        baseline_config=baseline_config, **parameters)


def _qualify_one(*, config, deployed_container, source_sha, evidence_dir, runtime_env,
                 baseline_proof=None, baseline_config=None):
    script = script_for(config)
    if runtime_env != {'FEEDBACK_DB_PATH': '/tmp/feedback.db'}:
        raise ValueError('browser QA requires fixed temporary database environment')
    if not SHA.fullmatch(source_sha):
        raise ValueError('invalid browser QA source SHA')
    deployed = inspect(deployed_container)
    image = deployed['Image']
    if (not IMAGE.fullmatch(image) or not deployed['State']['Running']
            or inspect(image, 'image')['Config']['Labels'].get('delivery-kit.source-sha') != source_sha):
        raise ValueError('browser QA deployment identity mismatch')
    identity = {'source_sha': source_sha, 'deployed_container_id': deployed['Id'],
                'application_image': image, 'config': config,
                'scenario_sha256': hashlib.sha256(script.read_bytes()).hexdigest(),
                'runtime_env': runtime_env}
    key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    directory = Path(evidence_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (key + '.json')
    if baseline_config is not None:
        composition.verify(directory, baseline_proof, identity, baseline_config,
                           hashlib.sha256(script_for(baseline_config).read_bytes()).hexdigest())
    elif baseline_proof is not None:
        raise ValueError('baseline QA operation required')
    if path.exists():
        if path.is_symlink() or path.stat().st_size > 65536:
            raise ValueError('unsafe browser QA receipt')
        existing = json.loads(path.read_text())
        if existing.get('identity') != identity:
            raise ValueError('browser QA receipt identity drift')
        if existing['status'] == 'passed':
            if existing.get('baseline_qa') != baseline_proof:
                raise ValueError('browser QA baseline binding drift')
            if (existing.get('cleanup') != 'passed' or existing.get('automated') is not True
                    or existing.get('result', {}).get('source_sha') != source_sha
                    or existing.get('result', {}).get('status') != 'passed'):
                raise ValueError('browser QA receipt incomplete')
            screenshot = directory / (key + '.png')
            if hashlib.sha256(screenshot.read_bytes()).hexdigest() != existing['screenshot_sha256']:
                raise ValueError('browser QA screenshot evidence drift')
            return existing
        cleanup(existing['resources'], existing['owner'])
        existing.update(status='blocked', next_action='quality_security diagnoses; new authorized attempt required')
        save_receipt(path, existing)
        raise ValueError('post-deploy browser QA previous attempt blocked')
    owner = 'delivery-kit-browser-' + uuid.uuid4().hex
    resources = [('network', owner), ('container', owner + '-app'), ('container', owner + '-browser')]
    receipt = {'status': 'running', 'identity': identity, 'owner': owner,
               'resources': resources, 'started_at': time.time(), 'automated': True}
    if baseline_proof is not None:
        receipt['baseline_qa'] = baseline_proof
    save_receipt(path, receipt)
    failure = None
    try:
        docker('network', 'create', '--internal', '--label', 'delivery-kit.browser-qa=' + owner, owner)
        env = [part for name, value in runtime_env.items() for part in ('--env', name + '=' + value)]
        docker('run', '-d', '--name', owner + '-app', '--network', owner,
               *docker_group_args('browser-fixture'),
               '--network-alias', 'fixture', '--label', 'delivery-kit.browser-qa=' + owner,
               '--read-only', '--tmpfs', '/tmp:rw,nosuid,nodev,size=8m', '--cap-drop', 'ALL',
               '--security-opt', 'no-new-privileges', '--memory', '128m', '--cpus', '0.5',
               '--pids-limit', '64', *env, image)
        # A fixed health probe waits for the isolated fixture, not a host-published service.
        for attempt in range(30):
            ready = docker('exec', owner + '-app', 'python', '-c',
                           'import urllib.request; urllib.request.urlopen("http://127.0.0.1:8080/health",timeout=1)',
                           check=False)
            if ready.returncode == 0:
                break
            time.sleep(0.2)
        else:
            raise ValueError('fixture startup deadline')
        output = docker('run', '--name', owner + '-browser', '--network', owner,
                        *docker_group_args('browser-runner'),
                        '--label', 'delivery-kit.browser-qa=' + owner, '--user', '10000:10000',
                        '--read-only', '--tmpfs', '/tmp:rw,nosuid,nodev,size=256m',
                        '--env', 'HOME=/tmp', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
                        '--memory', '768m', '--cpus', '1', '--pids-limit', '256',
                        '--shm-size', '128m', '--mount', 'type=bind,source=' + str(script) +
                        ',target=/scenario.py,readonly', '--entrypoint', 'python',
                        config['browser_image'], '/scenario.py', config['scenario'],
                        check=False, timeout=120)
        result = json.loads(output.stdout)
        if output.returncode or result.get('status') != 'passed' or result.get('source_sha') != source_sha:
            raise ValueError(result.get('error', 'browser evidence failed or SHA mismatch'))
        screenshot = base64.b64decode(result.pop('screenshot_base64'), validate=True)
        (directory / (key + '.png')).write_bytes(screenshot)
        receipt.update(result=result, screenshot_sha256=hashlib.sha256(screenshot).hexdigest())
        if baseline_config is not None:
            composition.verify(directory, baseline_proof, identity, baseline_config,
                               hashlib.sha256(script_for(baseline_config).read_bytes()).hexdigest())
    except Exception as error:
        failure = type(error).__name__ + ': ' + str(error)
    finally:
        try:
            cleanup(resources, owner)
            receipt['cleanup'] = 'passed'
        except Exception as error:
            failure = (failure or '') + ' cleanup: ' + str(error)
            receipt['cleanup'] = 'failed'
    receipt.update(status='failed' if failure else 'passed', finished_at=time.time())
    if failure:
        receipt.update(error=failure, next_action='quality_security diagnoses; no identical automatic retry')
    save_receipt(path, receipt)
    if failure:
        raise ValueError('post-deploy browser QA ' + failure)
    return receipt
