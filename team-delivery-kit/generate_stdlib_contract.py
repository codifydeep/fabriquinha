"""Derive C1 delivery controls from the Tech Lead card and verified Git base."""
import hashlib
import json
from pathlib import Path
import subprocess

from bootstrap_multica import BACKEND_PORT, PRIVATE
from evalctl import PROJECT
from planning_intake import parse_proposal
from portable_contract import is_test_path, safe_path, validate as validate_contract
from portable_run_spec import validate as validate_spec
from prepare_issue_base import verified_main
from project_selection import current as selected_project
from release_eval import save_receipt
from stdlib_replan import RUN


ROOT = Path(__file__).resolve().parent
REPO = ROOT / 'sandbox-github2'
CONTRACT_PATH = ROOT / 'projects' / 'pilot-feedback-board-c1.contract.json'
SPEC_PATH = ROOT / 'projects' / 'pilot-feedback-board-c1.run.json'
LABEL = 'FB-1'
PYTHON_RUNNER = ['python3', '-m', 'unittest', 'discover', '-s', '.', '-q']


def tracked_at(sha):
    names = subprocess.check_output(['git', '-C', str(REPO), 'ls-tree', '-r', '-z',
                                     '--name-only', sha]).decode().split('\0')
    result = sorted(name for name in names if name)
    if not result or len(result) > 110:
        raise ValueError('unsupported baseline tree size')
    for name in result:
        safe_path(name)
        path = REPO / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 32768:
            raise ValueError('unsupported baseline file')
    return result


def derive(card, tracked, runtime):
    if card['id'] != 'C1' or card['owner'] != 'backend_data' or card['depends_on']:
        raise ValueError('C1 is not an independent backend card')
    if card['test_command'] != PYTHON_RUNNER:
        raise ValueError('C1 test runner differs from qualified Python command')
    existing = set(tracked)
    editable = set(card['files'])
    if not {'app/server.py', 'tests/test_feedback_api.py'} <= editable:
        raise ValueError('C1 lacks server and independent API test')
    old_tests = {name for name in tracked if is_test_path(name, '.', 'python3')}
    new_tests = {name for name in editable - existing if is_test_path(name, '.', 'python3')}
    if not old_tests or not new_tests or old_tests & editable:
        raise ValueError('protected baseline or new C1 tests missing')
    if 'Dockerfile.feedback-bootstrap' not in existing:
        raise ValueError('bootstrap Dockerfile missing')
    contract = {
        'schema_version': 2, 'repository': 'codifydeep/descartavel2',
        'base_branch': 'main', 'files': sorted(existing | editable),
        'required_files': sorted(existing | set(card.get('required_files', card['files'])) | new_tests),
        'protected_files': sorted(existing - editable),
        'editable_files': sorted(editable),
        'test_files': sorted(old_tests | new_tests),
        'test_roots': ['.'], 'test_command': PYTHON_RUNNER,
        'test_image': runtime['test_image'],
        'test_success_pattern': r'(?m)^OK$',
        'test_count_pattern': r'Ran ([0-9]+) tests? in ',
        'qa_cases': [{'path': '/health', 'status': 200,
                      'expected_json': {'status': 'ok'}}],
    }
    validate_contract(contract)
    acceptance = '\n'.join('- ' + item for item in card['acceptance'])
    description = (
        'Disposable feedback-board C1 only. Work in /workspace and edit only '
        'contract-declared files. Allowed editable files: ' + ', '.join(sorted(editable)) + '. '
        'Deliver every required editable file, including new files: '
        + ', '.join(sorted(set(contract['required_files']) - existing)) + '. '
        'Follow Red-Green-Refactor: add the new API '
        'test before implementation, capture failing Red, passing Green and '
        'the complete suite. Preserve every existing test and protected file '
        'byte-for-byte. Use exactly: cd /workspace && PYTHONDONTWRITEBYTECODE=1 '
        'python3 -m unittest discover -s . -q 2>&1. Do not use network, '
        'Docker, GitHub or credentials. Acceptance from the Tech Lead:\n' + acceptance)
    review = (
        'Review only the frozen /delivery. Do not edit files or replay Red. '
        'Require evidence of new failing-then-passing API tests and verify the '
        'full suite; inspect rejection of blank/duplicate titles, idempotent '
        'completion, parameterized sqlite3 queries and persistence. Preserve '
        'all existing tests byte-for-byte. Finish with Decision: APPROVE or '
        'Decision: REQUEST_CHANGES;Reason: <specific finding>. '
        'No GitHub, Docker, credentials or other projects.\n' + acceptance)
    spec = {
        'label': LABEL, 'title': RUN + ' — C1 — ' + card['title'],
        'description': description, 'review_instruction': review,
        'qa_host_port': 19421, 'container_port': 8080,
        'dockerfile': 'Dockerfile.feedback-bootstrap',
        'implementer_registry': 'pilot-backend-data.json',
        'reviewer_registry': 'pilot-techlead-reviewer.json',
    }
    validate_spec(spec, contract)
    return contract, spec


def save_generated(path, value):
    if path.exists():
        if json.loads(path.read_text()) != value:
            raise ValueError('generated contract drift: ' + path.name)
    else:
        save_receipt(path, value)


def main():
    if PROJECT != 'delivery-kit-port2' or BACKEND_PORT != '19081':
        raise ValueError('C1 generation restricted to isolated port2')
    if selected_project()['repository'] != 'codifydeep/descartavel2' or selected_project()['checkout'] != REPO:
        raise ValueError('C1 generator requires the disposable feedback repository selection')
    plan = json.loads((PRIVATE / 'replans' / (RUN + '.json')).read_text())
    cards = json.loads((PRIVATE / 'planned-cards' / (RUN + '.json')).read_text())
    runtime = json.loads((ROOT / 'projects' / 'pilot-feedback-board.runtime.json').read_text())
    alignment = json.loads((PRIVATE / 'runtime-alignment' / 'PILOT-FEEDBACK-BOARD.json').read_text())
    if plan.get('stage') != 'plan_ready' or cards.get('stage') != 'blocked_execution_contract' or alignment.get('stage') != 'aligned':
        raise ValueError('approved plan, blocked card and aligned runtime required')
    if hashlib.sha256((ROOT / 'projects' / 'pilot-feedback-board.runtime.json').read_bytes()).hexdigest() != alignment['config_sha256']:
        raise ValueError('runtime config changed after alignment')
    proposal = parse_proposal(json.dumps(plan['proposal']), 'techlead')
    sha = verified_main()
    if sha != plan['bootstrap_sha'] or sha != cards['bootstrap_sha']:
        raise ValueError('main no longer matches reviewed bootstrap')
    contract, spec = derive(proposal['cards'][0], tracked_at(sha), runtime)
    save_generated(CONTRACT_PATH, contract)
    save_generated(SPEC_PATH, spec)
    receipt = {'stage': 'generated_not_dispatched', 'label': LABEL,
               'base_sha': sha, 'issue_id': cards['cards']['C1'],
               'plan_sha256': cards['plan_sha256'],
               'contract_sha256': hashlib.sha256(CONTRACT_PATH.read_bytes()).hexdigest(),
               'spec_sha256': hashlib.sha256(SPEC_PATH.read_bytes()).hexdigest()}
    save_receipt(PRIVATE / 'generated-contracts' / (LABEL + '.json'), receipt)
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
