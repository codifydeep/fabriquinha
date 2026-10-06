"""Controlled CTO-path qualification on disposable descartavel2 only.

The intentionally merged CSS MIME fault is proved in a running exact-SHA
container. The Tech Lead card is created but deliberately not dispatched; this
exercise qualifies the CTO branch, not two actual failed Tech Lead attempts.
"""
import argparse
import json
from pathlib import Path
import subprocess
import time

from bootstrap_multica import PRIVATE
from evalctl import BACKEND_PORT, PROJECT
from portable_qa_incident import record as record_incident
from portable_qa_cto import record as record_cto
from portable_qa_repair import parse_diagnosis
from portable_qualification import verify_docker_deployment
from portable_run_spec import validate as validate_spec
from prepare_issue_base import verified_main
from project_selection import current
from qa_postmerge_trial import derive_parent, digest, write_once
from start_eval import check_model_budget, cli, issue


LABEL = 'QACTO-1'
ERROR = 'post-deploy content type mismatch: /static/style.css'
CONTAINER = 'delivery-kit-port2-qacto-1-fault'
PORT = 19428


def paths():
    folder = PRIVATE / 'qa-cto-trial'
    return folder, folder / 'proof.json', folder / 'parent.contract.json', folder / 'parent.run.json'


def selected():
    project = current()
    if (PROJECT != 'delivery-kit-port2' or BACKEND_PORT != '19081'
            or project['repository'] != 'codifydeep/descartavel2'):
        raise ValueError('CTO trial restricted to isolated port2 descartavel2')
    return project, verified_main()


def parent_contract(project, sha):
    template = json.loads((Path(__file__).parent / 'projects' /
                           'pilot-feedback-board-c2.contract.json').read_text())
    tracked = subprocess.check_output(
        ['git', '-C', str(project['checkout']), 'ls-tree', '-r', '--name-only', sha],
        text=True).splitlines()
    contract, spec = derive_parent(tracked, template)
    spec.update(label=LABEL, title='QACTO-1 — controlled deployed CSS MIME fault',
                description=('Operator-seeded CTO branch qualification only. '
                             'The exact-SHA deployed image fails the unchanged '
                             '/static/style.css MIME contract. The Tech Lead '
                             'card is deliberately not dispatched. No success '
                             'for this parent SHA is permitted.'),
                qa_host_port=19429)
    validate_spec(spec, contract)
    return contract, spec


def proof(project, sha, contract):
    from portable_delivery import build_delivery_image
    folder, proof_path, _, _ = paths()
    image_contract = json.loads((Path(__file__).parent / 'projects' /
                                 'pilot-feedback-board-c2.contract.json').read_text())
    if image_contract['qa_cases'] != contract['qa_cases']:
        raise ValueError('CTO proof QA cases differ from parent')
    if subprocess.run(['docker', 'inspect', CONTAINER],
                      capture_output=True).returncode == 0:
        raise ValueError('CTO trial fault container already exists')
    tag = build_delivery_image(sha, image_contract,
                               dockerfile='Dockerfile.feedback-bootstrap',
                               image_name='delivery-kit-port2-ctofault')
    subprocess.run(['docker', 'run', '-d', '--rm', '--name', CONTAINER,
                    *__import__('docker_grouping').args('cto-fault', namespace='delivery-kit-port2'),
                    '--network', 'bridge', '--publish', f'127.0.0.1:{PORT}:8080',
                    '--read-only', '--tmpfs', '/tmp:rw,nosuid,nodev,size=8m',
                    '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
                    '--memory', '128m', '--cpus', '0.5', '--pids-limit', '64',
                    '--restart', 'no', tag], check=True, stdout=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                verify_docker_deployment(CONTAINER, f'http://127.0.0.1:{PORT}',
                                         sha, image_contract)
            except (OSError, ConnectionError):
                time.sleep(1)
                continue
            except ValueError as error:
                if str(error) != ERROR:
                    raise
                evidence = {'label': LABEL, 'repository': project['repository'],
                            'source_sha': sha, 'error': str(error),
                            'qa_cases_sha256': digest(contract['qa_cases'])}
                write_once(proof_path, evidence)
                return evidence
            raise ValueError('CTO trial unexpectedly passed deployed QA')
        raise TimeoutError('CTO trial container did not answer')
    finally:
        subprocess.run(['docker', 'stop', '--time', '2', CONTAINER],
                       check=False, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL)


def seed(project, sha, contract, spec):
    folder, proof_path, contract_path, spec_path = paths()
    if not proof_path.is_file() or proof_path.is_symlink():
        raise ValueError('CTO trial requires exact-SHA Docker QA proof')
    evidence = json.loads(proof_path.read_text())
    if (evidence.get('source_sha') != sha or evidence.get('error') != ERROR
            or evidence.get('qa_cases_sha256') != digest(contract['qa_cases'])):
        raise ValueError('CTO trial QA proof drift')
    write_once(contract_path, contract)
    write_once(spec_path, spec)
    parent = issue(spec['title'], spec['description'])
    context = {'label': LABEL, 'issue_id': parent['id'], 'base_sha': sha,
               'contract_sha256': digest(contract),
               'run_spec_sha256': digest(spec)}
    write_once(PRIVATE / ('portable-context-' + LABEL + '.json'), context)
    planning = json.loads((PRIVATE / 'planning-agents.json').read_text())['agents']
    incident = record_incident(
        PRIVATE, cli, context=context, label=LABEL, phase='deployed',
        source_sha=sha, error=ValueError(ERROR),
        techlead_id=planning['techlead'], budget_ready=False,
        parent_contract=contract)
    # This is a deliberately controlled branch injection; it does not claim
    # that the Tech Lead made two real invalid proposals.
    cto = record_cto(
        PRIVATE, cli, incident=incident, parent_contract=contract,
        cto_id=planning['cto'],
        reason='Controlled CTO-path qualification after verified Docker QA fault',
        budget_ready=True)
    receipt = {'label': LABEL, 'source_sha': sha,
               'parent_issue_id': parent['id'],
               'incident_issue_id': incident['child_issue_id'],
               'cto_issue_id': cto['child_issue_id'],
               'cto_dispatch': cto['dispatch'],
               'contract': str(contract_path), 'run_spec': str(spec_path)}
    write_once(folder / 'seed.json', receipt)
    return receipt


def reopen_after_safe_path_fix(project, sha, contract):
    """Audit one resumption of the same completed CTO proposal, no new call."""
    status_path = PRIVATE / 'autonomy-status' / (LABEL + '.json')
    if status_path.is_symlink() or not status_path.is_file():
        raise ValueError('CTO trial status missing')
    old = json.loads(status_path.read_text())
    recovery = old.get('recovery', {})
    if (old.get('stage') != 'cto_diagnosis_rejected'
            or recovery.get('reason') != 'QA repair new test path is unsafe'
            or old.get('label') != LABEL):
        raise ValueError('CTO trial is not at the audited parser rejection')
    receipt = json.loads((PRIVATE / 'qa-cto-trial' / 'seed.json').read_text())
    if (receipt['source_sha'] != sha
            or receipt['parent_issue_id'] != old['issue_id']
            or receipt['cto_issue_id'] != recovery['cto_issue_id']):
        raise ValueError('CTO trial restart identity drift')
    runs = [run for run in cli('runs', receipt['cto_issue_id'])
            if run.get('status') == 'completed']
    if len(runs) != 1:
        raise ValueError('CTO trial requires one completed proposal')
    tracked = subprocess.check_output(
        ['git', '-C', str(project['checkout']), 'ls-tree', '-r', '--name-only', sha],
        text=True).splitlines()
    proposal = parse_diagnosis(runs[0]['result']['output'], contract, tracked)
    if proposal['new_test_file'] != 'test_static_content_type.py':
        raise ValueError('unexpected CTO proposal after canonicalization')
    audit = {'label': LABEL, 'source_sha': sha,
             'cto_task_id': runs[0]['id'], 'prior_stage': old['stage'],
             'normalized_test_path': proposal['new_test_file'],
             'reason': 'single leading ./ normalized; traversal still rejected'}
    write_once(PRIVATE / 'qa-cto-trial' / 'safe-path-reopen.json', audit)
    return audit


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('proof', 'seed', 'reopen'))
    args = parser.parse_args()
    project, sha = selected()
    contract, spec = parent_contract(project, sha)
    if args.action == 'proof':
        print(json.dumps(proof(project, sha, contract), sort_keys=True))
    elif args.action == 'seed':
        check_model_budget()
        print(json.dumps(seed(project, sha, contract, spec), sort_keys=True))
    else:
        print(json.dumps(reopen_after_safe_path_fix(project, sha, contract),
                         sort_keys=True))


if __name__ == '__main__':
    main()
