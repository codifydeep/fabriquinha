"""Operator-owned recovery contract after FBTDD-2 failed local HTTP QA."""
import json
from pathlib import Path
import subprocess

from bootstrap_multica import PRIVATE
from portable_contract import is_test_path, validate as validate_contract
from portable_run_spec import validate as validate_spec
from prepare_issue_base import verified_main
from project_selection import current as selected_project
from release_eval import save_receipt
from start_eval import cli


ROOT = Path(__file__).resolve().parent
LABEL = 'FBFIX-1'
NEW_TEST = 'tests/test_static_mime.py'
CONTRACT = ROOT / 'projects' / 'pilot-feedback-board-qa-fix.contract.json'
SPEC = ROOT / 'projects' / 'pilot-feedback-board-qa-fix.run.json'


def derive(tracked, template):
    existing = set(tracked)
    if (NEW_TEST in existing or 'app/server.py' not in existing
            or 'tests/test_board_ui.py' not in existing
            or 'Dockerfile.feedback-bootstrap' not in existing):
        raise ValueError('QA fix baseline is not the merged C2 delivery')
    editable = {'app/server.py', NEW_TEST}
    tests = {name for name in existing if is_test_path(name, '.', 'python3')}
    contract = {**template,
                'files': sorted(existing | {NEW_TEST}),
                'required_files': sorted(existing | {NEW_TEST}),
                'protected_files': sorted(existing - editable),
                'editable_files': sorted(editable),
                'test_files': sorted(tests | {NEW_TEST})}
    validate_contract(contract)
    spec = {
        'label': LABEL,
        'title': 'PILOT-FEEDBACK-BOARD-STDLIB — QA correction — JavaScript MIME',
        'description': (
            'Disposable feedback-board QA correction on the merged C2 main. '
            'The approved HTTP contract requires GET /static/app.js to send '
            'Content-Type beginning application/javascript; the current server '
            'sends text/javascript. Phase 1 TESTS ONLY: add '
            'tests/test_static_mime.py with an executed assertion for the exact '
            'contractual MIME type. Do not edit app/server.py yet. The controller '
            'must freeze the test and observe Red against the pinned base. Phase 2 '
            'begins only after controller Red: change only app/server.py to meet the '
            'contract, preserving all routes and existing tests. Run exactly '
            'cd /workspace && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest '
            'discover -s . -q 2>&1. No GitHub, Docker, network or credentials in '
            'the worker. Do not modify or weaken any pre-existing test.'),
        'review_instruction': (
            'Review only the frozen /delivery and controller Red/Green receipts. '
            'Do not edit or replay Red. Require an exact MIME assertion in the '
            'new test, unchanged baseline tests, passing full suite, and no '
            'regression to GET /, static CSS or API routes. Run only the permitted '
            'validation. Finish with Decision: APPROVE or '
            'Decision: REQUEST_CHANGES;Reason: <specific finding>.'),
        'qa_host_port': 19425, 'container_port': 8080,
        'dockerfile': 'Dockerfile.feedback-bootstrap',
        'implementer_registry': 'pilot-frontend.json',
        'reviewer_registry': 'pilot-techlead-reviewer.json',
    }
    validate_spec(spec, contract)
    return contract, spec


def main():
    project = selected_project()
    if project['repository'] != 'codifydeep/descartavel2':
        raise ValueError('QA correction restricted to disposable repository')
    prior = json.loads((PRIVATE / 'release-receipts' / 'FBTDD-2.json').read_text())
    issue = cli('get', prior['issue_id'])
    if (issue['status'] != 'blocked'
            or issue.get('metadata', {}).get('execution_gate') != 'blocked_postdeploy_qa'
            or prior.get('merge_sha') != verified_main()
            or prior.get('deployment') is not None):
        raise ValueError('QA failure or current main identity changed')
    tracked = subprocess.check_output(
        ['git', '-C', str(project['checkout']), 'ls-tree', '-r', '--name-only',
         prior['merge_sha']], text=True).splitlines()
    template = json.loads((ROOT / 'projects' / 'pilot-feedback-board-c2.contract.json').read_text())
    contract, spec = derive(tracked, template)
    for path, value in ((CONTRACT, contract), (SPEC, spec)):
        if path.exists():
            if json.loads(path.read_text()) != value:
                raise ValueError('QA correction contract drift: ' + path.name)
        else:
            save_receipt(path, value)
    print(json.dumps({'label': LABEL, 'base_sha': prior['merge_sha'],
                      'contract': str(CONTRACT), 'run_spec': str(SPEC)}))


if __name__ == '__main__':
    main()
