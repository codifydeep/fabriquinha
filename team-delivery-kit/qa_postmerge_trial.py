"""Operator-seeded, disposable post-merge QA recovery qualification.

The known fault is merged separately by a labeled PR in descartavel2. This
script proves the running exact-SHA image fails the unchanged HTTP contract,
then (only in `seed`) creates a blocked synthetic parent and a durable Tech
Lead incident. It never starts an agent or modifies another repository.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

from bootstrap_multica import PRIVATE
from portable_contract import is_test_path, validate as validate_contract
from portable_qa_incident import find as find_incident, record
from portable_qa_diagnosis_retry import find as find_retry
from portable_qa_repair import parse_diagnosis
from portable_qualification import verify_docker_deployment
from portable_run_spec import validate as validate_spec
from prepare_issue_base import verified_main
from project_selection import current as selected_project
from release_eval import save_receipt
from start_eval import cli, issue


ROOT = Path(__file__).resolve().parent
LABEL = 'QAINC-1'
CONTAINER = 'delivery-kit-port2-qainc-1-fault'
PORT = 19426
EXPECTED_ERROR = 'post-deploy content type mismatch: /static/app.js'
PLACEHOLDER = 'tests/test_qa_parent_placeholder.py'


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True,
                          separators=(',', ':')).encode()).hexdigest()


def write_once(path, value):
    if path.exists():
        if path.is_symlink() or json.loads(path.read_text()) != value:
            raise ValueError('QA fault trial artifact drift: ' + path.name)
    else:
        save_receipt(path, value)


def derive_parent(tracked, template):
    existing = set(tracked)
    tests = {name for name in existing if any(
        is_test_path(name, root, template['test_command'][0])
        for root in template['test_roots'])}
    if (PLACEHOLDER in existing or not tests or 'tests/test_static_mime.py' not in tests
            or 'app/server.py' not in existing
            or not set(template['protected_files']) <= existing):
        raise ValueError('fault trial baseline does not match repaired feedback board')
    editable = {'app/server.py', PLACEHOLDER}
    files = existing | {PLACEHOLDER}
    contract = {**template,
                'files': sorted(files), 'required_files': sorted(files),
                'protected_files': sorted(existing - editable),
                'editable_files': sorted(editable),
                'test_files': sorted(tests | {PLACEHOLDER})}
    validate_contract(contract)
    spec = {
        'label': LABEL,
        'title': 'QAINC-1 — disposable deployed-only MIME fault qualification',
        'description': (
            'Operator-seeded QA incident only. This parent is not an author card. '
            'The disposable deployed image fails the unchanged /static/app.js '
            'Content-Type contract. The Tech Lead diagnosis must create a new '
            'pinned TDD correction card. Do not mark this SHA as QA passed.'),
        'review_instruction': (
            'Only a new exact-SHA repair delivery may be independently reviewed. '
            'Never approve or modify the failed parent delivery.'),
        'qa_host_port': 19427, 'container_port': 8080,
        'dockerfile': 'Dockerfile.feedback-bootstrap',
        'implementer_registry': 'pilot-frontend.json',
        'reviewer_registry': 'pilot-techlead-reviewer.json',
    }
    validate_spec(spec, contract)
    return contract, spec


def project_and_sha():
    from evalctl import PROJECT
    project = selected_project()
    if PROJECT != 'delivery-kit-port2' or project['repository'] != 'codifydeep/descartavel2':
        raise ValueError('QA fault trial restricted to isolated descartavel2')
    sha = verified_main()
    return project, sha


def proof(project, sha, template):
    """Verify actual Docker/HTTP failure, then remove only this test container."""
    from portable_delivery import build_delivery_image
    if subprocess.run(['docker', 'inspect', CONTAINER], capture_output=True).returncode == 0:
        raise ValueError('fault trial container already exists')
    tag = build_delivery_image(sha, template,
                               dockerfile='Dockerfile.feedback-bootstrap',
                               image_name='delivery-kit-port2-qafault')
    subprocess.run(['docker', 'run', '-d', '--rm', '--name', CONTAINER,
                    *__import__('docker_grouping').args('qa-fault', namespace='delivery-kit-port2'),
                    '--network', 'bridge', '--publish', f'127.0.0.1:{PORT}:8080',
                    '--read-only', '--tmpfs', '/tmp:rw,nosuid,nodev,size=8m',
                    '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
                    '--memory', '128m', '--cpus', '0.5', '--pids-limit', '64',
                    '--restart', 'no', tag], check=True, stdout=subprocess.DEVNULL)
    url = f'http://127.0.0.1:{PORT}'
    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                verify_docker_deployment(CONTAINER, url, sha, template)
            except (OSError, ConnectionError):
                time.sleep(1)
                continue
            except ValueError as error:
                if str(error) != EXPECTED_ERROR:
                    raise
                evidence = {'label': LABEL, 'repository': project['repository'],
                            'source_sha': sha, 'error': str(error),
                            'qa_cases_sha256': digest(template['qa_cases']),
                            'container': CONTAINER, 'url': url}
                path = PRIVATE / 'qa-fault-trial' / 'proof.json'
                write_once(path, evidence)
                return evidence
            raise ValueError('fault trial unexpectedly passed deployed QA')
        raise TimeoutError('fault trial deployment did not answer')
    finally:
        subprocess.run(['docker', 'stop', '--time', '2', CONTAINER],
                       check=False, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL)


def seed(project, sha, template):
    path = PRIVATE / 'qa-fault-trial' / 'proof.json'
    if not path.is_file() or path.is_symlink():
        raise ValueError('exact-SHA Docker QA proof required before incident')
    evidence = json.loads(path.read_text())
    if (evidence.get('source_sha') != sha
            or evidence.get('repository') != project['repository']
            or evidence.get('error') != EXPECTED_ERROR
            or evidence.get('qa_cases_sha256') != digest(template['qa_cases'])):
        raise ValueError('fault trial proof identity drift')
    tracked = subprocess.check_output(
        ['git', '-C', str(project['checkout']), 'ls-tree', '-r', '--name-only', sha],
        text=True).splitlines()
    contract, spec = derive_parent(tracked, template)
    folder = PRIVATE / 'qa-fault-trial'
    contract_path = folder / 'parent.contract.json'
    spec_path = folder / 'parent.run.json'
    write_once(contract_path, contract)
    write_once(spec_path, spec)
    parent = issue(spec['title'], spec['description'])
    context = {'label': LABEL, 'issue_id': parent['id'], 'base_sha': sha,
               'contract_sha256': digest(contract), 'run_spec_sha256': digest(spec)}
    write_once(PRIVATE / ('portable-context-' + LABEL + '.json'), context)
    planning = json.loads((PRIVATE / 'planning-agents.json').read_text())['agents']
    incident = record(PRIVATE, cli, context=context, label=LABEL,
                      phase='deployed', source_sha=sha,
                      error=ValueError(EXPECTED_ERROR),
                      techlead_id=planning['techlead'], budget_ready=False,
                      parent_contract=contract)
    return {'label': LABEL, 'source_sha': sha,
            'parent_issue_id': parent['id'], 'incident_issue_id': incident['child_issue_id'],
            'contract': str(contract_path), 'run_spec': str(spec_path),
            'dispatch': incident['dispatch']}


def reopen_after_case_match_fix(sha):
    """One audited retry after the controller confused '/' with '/static/*'."""
    path = PRIVATE / 'autonomy-status' / (LABEL + '.json')
    if not path.is_file() or path.is_symlink():
        raise ValueError('QA trial status unavailable')
    old = json.loads(path.read_text())
    category = ('ValueError:QA diagnosis retry lacks a precise operator contract')
    if (old.get('stage') != 'qa_repair_escalation'
            or old.get('recovery', {}).get('category') != category
            or old.get('label') != LABEL):
        raise ValueError('QA trial is not at the exact repaired controller defect')
    incident = find_incident(PRIVATE, old['issue_id'], LABEL)
    if not incident:
        raise ValueError('QA trial incident missing')
    if incident['source_sha'] != sha or incident['parent_issue_id'] != old['issue_id']:
        raise ValueError('QA trial incident identity drift')
    audit = {'label': LABEL, 'source_sha': sha,
             'prior_status': old, 'reason': 'exact QA case matching fixed; root / no longer shadows /static/app.js'}
    write_once(PRIVATE / 'qa-fault-trial' / 'case-match-reopen.json', audit)
    save_receipt(path, {'label': LABEL, 'stage': 'qa_blocked',
                        'issue_id': old['issue_id'], 'owner': 'techlead',
                        'category': incident['category'],
                        'reopened_from': category, 'updated_at': time.time()})
    return {'stage': 'qa_blocked', 'source_sha': sha,
            'incident_issue_id': incident['child_issue_id']}


def reopen_after_diagnosis_bound_fix(project, sha):
    """Accept a previously rejected proposal only after full revalidation."""
    path = PRIVATE / 'autonomy-status' / (LABEL + '.json')
    if not path.is_file() or path.is_symlink():
        raise ValueError('QA trial status unavailable')
    old = json.loads(path.read_text())
    if (old.get('label') != LABEL or old.get('stage') != 'cto_escalation_required'
            or old.get('recovery', {}).get('reason') !=
            'QA diagnosis requires a bounded root cause'):
        raise ValueError('QA trial is not at the exact diagnosis-bound blocker')
    incident = find_incident(PRIVATE, old['issue_id'], LABEL)
    if not incident or incident['source_sha'] != sha:
        raise ValueError('QA trial incident identity drift')
    retry = find_retry(PRIVATE, incident['key'])
    if not retry or retry['child_issue_id'] != old['recovery']['retry_issue_id']:
        raise ValueError('QA diagnosis retry identity drift')
    runs = [run for run in cli('runs', retry['child_issue_id'])
            if run.get('agent_id') == incident['techlead_id']
            and run.get('status') == 'completed']
    if len(runs) != 1:
        raise ValueError('one completed retry task required')
    output = runs[0].get('result', {}).get('output')
    contract = json.loads((PRIVATE / 'qa-fault-trial' / 'parent.contract.json').read_text())
    tracked = subprocess.check_output(
        ['git', '-C', str(project['checkout']), 'ls-tree', '-r', '--name-only', sha],
        text=True).splitlines()
    proposal = parse_diagnosis(output, contract, tracked)
    if proposal['decision'] != 'repair':
        raise ValueError('validated retry did not propose a repair')
    audit = {'label': LABEL, 'source_sha': sha, 'prior_status': old,
             'retry_task_id': runs[0]['id'], 'diagnosis_sha256': digest(proposal),
             'reason': 'non-operative root_cause bound raised to 1000; all paths and QA policy revalidated'}
    write_once(PRIVATE / 'qa-fault-trial' / 'diagnosis-bound-reopen.json', audit)
    save_receipt(path, {'label': LABEL, 'stage': 'qa_blocked',
                        'issue_id': old['issue_id'], 'owner': 'techlead',
                        'category': incident['category'],
                        'reopened_from': old['recovery']['reason'],
                        'updated_at': time.time()})
    return {'stage': 'qa_blocked', 'source_sha': sha,
            'validated_retry_task_id': runs[0]['id']}


def reopen_after_child_main_fix(sha):
    """Reverify the child SHA before reopening a false main-moved blocker."""
    path = PRIVATE / 'autonomy-status' / (LABEL + '.json')
    old = json.loads(path.read_text())
    if (old.get('label') != LABEL or old.get('stage') != 'main_moved_replan_required'):
        raise ValueError('QA trial is not at the child-main restart blocker')
    incident = find_incident(PRIVATE, old['issue_id'], LABEL)
    if not incident or incident['source_sha'] == sha:
        raise ValueError('QA trial child main identity invalid')
    label = 'QA' + incident['key'][:8].upper() + '-1'
    child = json.loads((PRIVATE / 'release-receipts' / (label + '.json')).read_text())
    if (child.get('label') != label or child.get('base_sha') != incident['source_sha']
            or child.get('merge_sha') != sha
            or child.get('stage') != 'deployed_qa_passed'):
        raise ValueError('exact successful child receipt required')
    audit = {'label': LABEL, 'source_sha': sha, 'prior_status': old,
             'child_label': label, 'child_pr_url': child['pr_url'],
             'reason': 'controller now recognizes exact successful repair child as current main'}
    write_once(PRIVATE / 'qa-fault-trial' / 'child-main-reopen.json', audit)
    save_receipt(path, {'label': LABEL, 'stage': 'qa_blocked',
                        'issue_id': old['issue_id'], 'owner': 'techlead',
                        'category': incident['category'],
                        'reopened_from': 'main_moved_replan_required',
                        'updated_at': time.time()})
    return {'stage': 'qa_blocked', 'source_sha': sha, 'child_label': label}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('proof', 'seed', 'reopen', 'reopen-bound',
                                          'reopen-child-main'))
    args = parser.parse_args()
    project, sha = project_and_sha()
    template = json.loads((ROOT / 'projects/pilot-feedback-board-c2.contract.json').read_text())
    validate_contract(template)
    result = (proof(project, sha, template) if args.action == 'proof'
              else seed(project, sha, template) if args.action == 'seed'
              else reopen_after_case_match_fix(sha) if args.action == 'reopen'
              else reopen_after_diagnosis_bound_fix(project, sha)
              if args.action == 'reopen-bound'
              else reopen_after_child_main_fix(sha))
    print(json.dumps(result, sort_keys=True), flush=True)


if __name__ == '__main__':
    main()
