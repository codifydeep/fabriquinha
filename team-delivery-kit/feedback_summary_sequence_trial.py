"""Prepare a disposable API-to-browser dependent delivery with frozen TDD tests."""
import json
from pathlib import Path
import subprocess

from evalctl import BACKEND_PORT, PRIVATE, PROJECT
from portable_contract import is_test_path, validate as validate_contract
from portable_run_spec import validate as validate_spec
from prepare_issue_base import verified_main
from project_selection import current
from qa_postmerge_trial import digest, write_once
from start_eval import check_model_budget


ROOT = Path(__file__).resolve().parent
PROJECTS = ROOT / 'projects'
TEMPLATE = PROJECTS / 'pilot-feedback-board-c2.contract.json'
SEQUENCE = 'FEEDBACK-SUMMARY-2'
API_TEST = 'test_feedback_summary_api.py'
UI_TEST = 'tests/test_feedback_summary_ui.py'


def prepare():
    project = current()
    if (PROJECT != 'delivery-kit-port2' or BACKEND_PORT != '19081'
            or project['repository'] != 'codifydeep/descartavel2'):
        raise ValueError('feedback summary trial restricted to port2 descartavel2')
    budget = check_model_budget()
    if budget['remaining'] < 128:
        raise ValueError('dependent TDD trial requires 128 available model calls')
    base_sha = verified_main()
    tracked = set(subprocess.check_output([
        'git', '-C', str(project['checkout']), 'ls-tree', '-r', '--name-only',
        base_sha], text=True).splitlines())
    if ({API_TEST, UI_TEST} & tracked or
            not {'app/server.py', 'app/static/index.html', 'app/static/app.js',
                 'Dockerfile.feedback-bootstrap', 'tests/test_board_ui.py'} <= tracked):
        raise ValueError('feedback summary trial baseline changed')
    if '/feedback/summary' in (project['checkout'] / 'app/server.py').read_text():
        raise ValueError('feedback summary route already exists')
    template = json.loads(TEMPLATE.read_text())
    old_tests = {name for name in tracked if is_test_path(name, '.', 'python3')}
    api_files = tracked | {API_TEST}
    api_editable = {'app/server.py', API_TEST}
    qa_summary = {'path': '/feedback/summary', 'status': 200,
                  'expected_json': {'total': 0, 'completed': 0, 'open': 0},
                  'bind_source_sha': False}
    api_contract = {
        **template,
        'files': sorted(api_files), 'required_files': sorted(api_files),
        'protected_files': sorted(api_files - api_editable),
        'editable_files': sorted(api_editable),
        'test_files': sorted(old_tests | {API_TEST}),
        'qa_cases': [*template['qa_cases'], qa_summary],
    }
    ui_files = api_files | {UI_TEST}
    ui_editable = {'app/static/index.html', 'app/static/app.js', UI_TEST}
    ui_contract = {
        **template,
        'files': sorted(ui_files), 'required_files': sorted(ui_files),
        'protected_files': sorted(ui_files - ui_editable),
        'editable_files': sorted(ui_editable),
        'test_files': sorted(old_tests | {API_TEST, UI_TEST}),
        'qa_cases': [*api_contract['qa_cases'],
                     {'path': '/', 'status': 200, 'content_type': 'text/html',
                      'text_contains': ['id="feedback-summary"']},
                     {'path': '/static/app.js', 'status': 200,
                      'content_type': 'application/javascript',
                      'text_contains': ['/feedback/summary', 'feedback-summary']}],
    }
    validate_contract(api_contract)
    validate_contract(ui_contract)
    command = ('cd /workspace && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest '
               'discover -s . -q 2>&1')
    api_spec = {
        'label': 'SUMA-2',
        'title': 'SUMA-2 — feedback counts API with test-first evidence',
        'description': (
            'Disposable product slice, first of two dependent cards. Add GET '
            '/feedback/summary. Return exact JSON with integer total, '
            'completed, and open counts; open equals total minus completed. '
            'Use the existing SQLite persistence; count existing feedback '
            'items and changes after completion. Preserve all existing routes, '
            'static behavior and tests. PHASE 1 TESTS ONLY: create '
            + API_TEST + ' with real HTTP assertions for empty, created, and '
            'completed states; observe controller Red before changing '
            'app/server.py. PHASE 2: edit only app/server.py for Green. Run '
            'the complete pinned suite exactly: ' + command + '. No network, '
            'GitHub, Docker, credentials, or other projects in the worker.'),
        'review_instruction': (
            'Review immutable /delivery only. Check actual Red/Green receipts, '
            'preservation of all baseline tests, integer summary counts on '
            'empty/created/completed data, existing route behavior, and full '
            'suite. Do not edit or replay Red. Finish with Decision: APPROVE '
            'or Decision: REQUEST_CHANGES;Reason: <specific finding>.'),
        'qa_host_port': 19434, 'container_port': 8080,
        'dockerfile': 'Dockerfile.feedback-bootstrap',
        'implementer_registry': 'pilot-backend-data.json',
        'reviewer_registry': 'pilot-techlead-reviewer.json',
        'runtime_env': {'FEEDBACK_DB_PATH': '/tmp/feedback.db'},
    }
    ui_spec = {
        'label': 'SUMB-2',
        'title': 'SUMB-2 — display feedback counts in browser',
        'description': (
            'Disposable product slice, dependent on SUMA-2 merged, green and '
            'deployed. Add an accessible feedback summary region to the '
            'existing board. It displays total, open and completed counts '
            'fetched from GET /feedback/summary; refresh it after initial '
            'load, submit, completion and polling. Preserve the current form, '
            'list, errors, polling and all existing tests. PHASE 1 TESTS ONLY: '
            'create ' + UI_TEST + ' with executed assertions for the served '
            'summary markup, client endpoint wiring and refresh paths; '
            'observe controller Red before editing static assets. PHASE 2: '
            'edit only app/static/index.html and app/static/app.js. No '
            'stylesheets or backend changes. Run the complete pinned suite '
            'exactly: ' + command + '. No network, GitHub, Docker, credentials '
            'or other projects in the worker.'),
        'review_instruction': (
            'Review immutable /delivery only. Verify the prior SUMA-2 test '
            'is byte-identical, its API remains functional, new UI test had '
            'actual Red and Green receipts, and summary refreshes after '
            'initial load, submit, completion and polling without regressing '
            'the board. Run only controlled full-suite validation. Finish with '
            'Decision: APPROVE or Decision: REQUEST_CHANGES;Reason: '
            '<specific finding>.'),
        'qa_host_port': 19435, 'container_port': 8080,
        'dockerfile': 'Dockerfile.feedback-bootstrap',
        'implementer_registry': 'pilot-frontend.json',
        'reviewer_registry': 'pilot-techlead-reviewer.json',
        'runtime_env': {'FEEDBACK_DB_PATH': '/tmp/feedback.db'},
    }
    validate_spec(api_spec, api_contract)
    validate_spec(ui_spec, ui_contract)
    outputs = {
        'descartavel2-summary-slice-v2-api.contract.json': api_contract,
        'descartavel2-summary-slice-v2-api.run.json': api_spec,
        'descartavel2-summary-slice-v2-ui.contract.json': ui_contract,
        'descartavel2-summary-slice-v2-ui.run.json': ui_spec,
        'descartavel2-summary-slice-v2.sequence.json': {
            'sequence': SEQUENCE,
            'project_config': 'descartavel2.json',
            'stages': [
                {'contract': 'descartavel2-summary-slice-v2-api.contract.json',
                 'run_spec': 'descartavel2-summary-slice-v2-api.run.json',
                 'depends_on': None},
                {'contract': 'descartavel2-summary-slice-v2-ui.contract.json',
                 'run_spec': 'descartavel2-summary-slice-v2-ui.run.json',
                 'depends_on': 'SUMA-2'},
            ],
        },
    }
    for name, payload in outputs.items():
        write_once(PROJECTS / name, payload)
    receipt = {'sequence': SEQUENCE, 'base_sha': base_sha,
               'artifacts': {name: digest(payload) for name, payload in outputs.items()},
               'model_calls_at_preparation': budget['calls'],
               'model_call_ceiling': budget['max_calls']}
    write_once(PRIVATE / 'feedback-summary-slice-v2' / 'prepared.json', receipt)
    return receipt


if __name__ == '__main__':
    print(json.dumps(prepare(), sort_keys=True))
