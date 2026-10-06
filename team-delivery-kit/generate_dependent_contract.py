"""Pin the Tech Lead's C2 revision to the delivered C1 main and local runtime."""
import hashlib
import json
from pathlib import Path
import subprocess

from bootstrap_multica import BACKEND_PORT, PRIVATE
from dependent_replan import ISSUE, C1, LEDGER, COMMAND
from evalctl import PROJECT
from portable_contract import is_test_path, validate as validate_contract
from portable_run_spec import validate as validate_spec
from prepare_issue_base import verified_main
from project_selection import current as selected_project
from release_eval import save_receipt
from start_eval import cli
from stdlib_replan import RUN


ROOT = Path(__file__).resolve().parent
CONTRACT = ROOT / 'projects' / 'pilot-feedback-board-c2.contract.json'
SPEC = ROOT / 'projects' / 'pilot-feedback-board-c2.run.json'


def derive(card, tracked, runtime):
    existing = set(tracked)
    editable = set(card['files'])
    new_tests = {name for name in editable - existing if is_test_path(name, '.', 'python3')}
    old_tests = {name for name in existing if is_test_path(name, '.', 'python3')}
    if (card['id'] != 'C2' or card['owner'] != 'frontend' or card['depends_on'] != ['C1']
            or card['test_command'] != COMMAND or 'app/server.py' not in existing
            or editable & old_tests or new_tests != {'tests/test_board_ui.py'}
            or not editable - existing or not old_tests
            or 'Dockerfile.feedback-bootstrap' not in existing):
        raise ValueError('C2 revision is not compatible with C1 main')
    data = {
        'schema_version': 2, 'repository': 'codifydeep/descartavel2',
        'base_branch': 'main', 'files': sorted(existing | editable),
        'required_files': sorted(existing | set(card['required_files'])),
        'protected_files': sorted(existing - editable),
        'editable_files': sorted(editable), 'test_files': sorted(old_tests | new_tests),
        'test_roots': ['.'], 'test_command': COMMAND,
        'test_image': runtime['test_image'], 'test_success_pattern': r'(?m)^OK$',
        'test_count_pattern': r'Ran ([0-9]+) tests? in ',
        'qa_cases': [
            {'path': '/health', 'status': 200, 'expected_json': {'status': 'ok'}},
            {'path': '/', 'status': 200, 'content_type': 'text/html',
             'text_contains': ['<html', '<form']},
            {'path': '/static/app.js', 'status': 200, 'content_type': 'application/javascript',
             'text_contains': ['/feedback']},
            {'path': '/static/style.css', 'status': 200, 'content_type': 'text/css',
             'text_contains': ['{']},
        ],
    }
    validate_contract(data)
    acceptance = ' '.join(card['acceptance'])
    description = (
        'C2 frontend delivery for the disposable feedback board. Edit only the '
        'contract-declared paths in /workspace. Deliver app/server.py, '
        'app/static/index.html, app/static/app.js, app/static/style.css and '
        'tests/test_board_ui.py. Extend the existing stdlib server with GET / '
        'and /static/* while preserving C1 API routes. Serve HTML, JavaScript '
        'and CSS with correct content types and reject path traversal. The HTML '
        'must contain <html and <form; app.js must contain /feedback. Use '
        'Red-Green-Refactor and run EXACTLY: cd /workspace && '
        'PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s . -q 2>&1. '
        'Preserve every pre-existing test and protected file byte-for-byte. '
        'No network, Docker, GitHub or credentials. Tech Lead acceptance: ' + acceptance)
    review = (
        'Review only the frozen /delivery. Never edit or replay Red. Require '
        'actual failing-then-passing test receipts and the full suite. Check '
        'GET /, static content types, traversal rejection, the original API '
        'and all product behaviors in the C2 acceptance. Preserve all baseline '
        'tests byte-for-byte. Finish with Decision: APPROVE or '
        'Decision: REQUEST_CHANGES;Reason: <specific finding>. No GitHub, '
        'Docker or credentials. Acceptance: ' + acceptance)
    spec = {'label': 'FB-2', 'title': RUN + ' — C2 — ' + card['title'],
            'description': description, 'review_instruction': review,
            'qa_host_port': 19422, 'container_port': 8080,
            'dockerfile': 'Dockerfile.feedback-bootstrap',
            'implementer_registry': 'pilot-frontend.json',
            'reviewer_registry': 'pilot-techlead-reviewer.json'}
    validate_spec(spec, data)
    return data, spec


def save_generated(path, value):
    if path.exists():
        if json.loads(path.read_text()) != value:
            raise ValueError('generated C2 contract drift: ' + path.name)
    else:
        save_receipt(path, value)


def main():
    if PROJECT != 'delivery-kit-port2' or BACKEND_PORT != '19081':
        raise ValueError('C2 contract restricted to port2')
    selected = selected_project()
    if selected['repository'] != 'codifydeep/descartavel2':
        raise ValueError('C2 project identity mismatch')
    replan = json.loads(LEDGER.read_text())
    c1 = json.loads((PRIVATE / 'release-receipts' / 'FB-1.json').read_text())
    planned = json.loads((PRIVATE / 'planned-cards' / (RUN + '.json')).read_text())
    runtime_path = ROOT / 'projects' / 'pilot-feedback-board.runtime.json'
    runtime = json.loads(runtime_path.read_text())
    alignment = json.loads((PRIVATE / 'runtime-alignment' / 'PILOT-FEEDBACK-BOARD.json').read_text())
    sha = verified_main()
    if (replan['stage'] != 'decision_validated' or replan['base_sha'] != sha
            or c1['stage'] != 'deployed_qa_passed' or c1['merge_sha'] != sha
            or planned['cards']['C1'] != C1 or planned['cards']['C2'] != ISSUE
            or alignment['stage'] != 'aligned'
            or hashlib.sha256(runtime_path.read_bytes()).hexdigest() != alignment['config_sha256']):
        raise ValueError('C2 dependency, main or runtime alignment changed')
    names = subprocess.check_output(['git', '-C', str(selected['checkout']), 'ls-tree',
                                     '-r', '--name-only', sha], text=True).splitlines()
    contract, spec = derive(replan['card'], names, runtime)
    save_generated(CONTRACT, contract)
    save_generated(SPEC, spec)
    issue = cli('get', ISSUE)
    meta = cli('metadata', 'list', ISSUE)
    original = json.loads((PRIVATE / 'replans' / (RUN + '.json')).read_text())['proposal']['cards'][1]
    if (issue['status'] != 'blocked' or issue.get('assignee_id') is not None
            or issue['title'] != spec['title']
            or meta.get('execution_gate') != 'awaiting_generated_contract'
            or meta.get('planning_sha256') != planned['plan_sha256']
            or (issue['description'] != spec['description'] and
                ('Proposed files: ' + json.dumps(original['files'], ensure_ascii=False))
                not in issue['description'])):
        raise ValueError('C2 board card is not safely revisable')
    target = PRIVATE / 'generated-contracts' / 'FB-2.json'
    prior = json.loads(target.read_text()) if target.exists() else None
    old_digest = (prior['old_description_sha256'] if prior else
                  hashlib.sha256(issue['description'].encode()).hexdigest())
    receipt = {'stage': 'updating_board', 'label': 'FB-2', 'issue_id': ISSUE,
               'base_sha': sha, 'decision_task': replan['task_id'],
               'old_description_sha256': old_digest,
               'contract_sha256': hashlib.sha256(CONTRACT.read_bytes()).hexdigest(),
               'spec_sha256': hashlib.sha256(SPEC.read_bytes()).hexdigest()}
    if prior and {k: v for k, v in prior.items() if k != 'stage'} != {
            k: v for k, v in receipt.items() if k != 'stage'}:
        raise ValueError('C2 generation receipt drift')
    save_receipt(target, receipt)
    if issue['description'] != spec['description']:
        cli('update', ISSUE, '--description', spec['description'], '--no-start')
    revised = cli('get', ISSUE)
    if revised['description'] != spec['description']:
        raise ValueError('C2 board description update not confirmed')
    note = json.loads(meta['technical_blocker'])
    if note.get('kind') != 'contract_dependency_mismatch':
        raise ValueError('C2 blocker identity mismatch')
    note.update(status='resolved', decision_task=replan['task_id'],
                revised_contract_sha256=hashlib.sha256(CONTRACT.read_bytes()).hexdigest())
    cli('metadata', 'set', ISSUE, '--key', 'technical_blocker',
        '--value', json.dumps(note, sort_keys=True), '--type', 'string')
    receipt['stage'] = 'generated_not_dispatched'
    save_receipt(target, receipt)
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
