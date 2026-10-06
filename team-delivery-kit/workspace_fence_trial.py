"""One disposable end-to-end TDD card through the routed worker file fence."""
import json
from pathlib import Path
import subprocess

from bootstrap_multica import PRIVATE
from evalctl import BACKEND_PORT, PROJECT
from portable_contract import is_test_path, validate as validate_contract
from portable_run_spec import validate as validate_spec
from prepare_issue_base import verified_main
from project_selection import current
from qa_postmerge_trial import digest, write_once
from start_eval import check_model_budget


LABEL = 'FENCE-1'
NEW_TEST = 'test_ready_endpoint.py'
FOLDER = PRIVATE / 'workspace-fence-trial'
TEMPLATE = Path(__file__).parent / 'projects' / 'pilot-feedback-board-c2.contract.json'


def prepare():
    project = current()
    if (PROJECT != 'delivery-kit-port2' or BACKEND_PORT != '19081'
            or project['repository'] != 'codifydeep/descartavel2'):
        raise ValueError('fence trial restricted to isolated port2 descartavel2')
    check_model_budget()
    sha = verified_main()
    tracked = set(subprocess.check_output([
        'git', '-C', str(project['checkout']), 'ls-tree', '-r', '--name-only', sha],
        text=True).splitlines())
    if (NEW_TEST in tracked or 'app/server.py' not in tracked
            or 'Dockerfile.feedback-bootstrap' not in tracked
            or not {'tests/test_board_ui.py', 'test_static_content_type.py'} <= tracked):
        raise ValueError('fence trial baseline changed')
    if "path == '/ready'" in (project['checkout'] / 'app/server.py').read_text():
        raise ValueError('ready endpoint already present')
    template = json.loads(TEMPLATE.read_text())
    old_tests = {name for name in tracked if is_test_path(name, '.', 'python3')}
    files = tracked | {NEW_TEST}
    contract = {**template,
                'files': sorted(files), 'required_files': sorted(files),
                'protected_files': sorted(tracked - {'app/server.py'}),
                'editable_files': ['app/server.py', NEW_TEST],
                'test_files': sorted(old_tests | {NEW_TEST}),
                'qa_cases': [*template['qa_cases'],
                    {'path': '/ready', 'status': 200,
                     'expected_json': {'status': 'ready'}}]}
    validate_contract(contract)
    command = 'cd /workspace && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s . -q 2>&1'
    spec = {
        'label': LABEL,
        'title': 'FENCE-1 — disposable GET /ready TDD delivery',
        'description': (
            'Disposable infrastructure qualification. Add GET /ready to the '
            'existing stdlib HTTP server in app/server.py. It returns HTTP 200 '
            'and JSON {"status":"ready","source_sha":<SOURCE_SHA or "local">}. '
            'Preserve GET /health, feedback routes, static serving and every '
            'pre-existing test byte-for-byte. PHASE 1 TESTS ONLY: create '
            + NEW_TEST + ' with an executed failing regression assertion for '
            'GET /ready; observe Red before changing app/server.py. PHASE 2: '
            'change only app/server.py to make the frozen test Green. Run the '
            'complete pinned suite using exactly: ' + command + '. No network, '
            'GitHub, Docker, credentials or other projects in the worker.'),
        'review_instruction': (
            'Review only the immutable /delivery. Do not edit or replay Red. '
            'Require the controller Red/Green receipts, a genuine assertion '
            'for GET /ready in ' + NEW_TEST + ', exact expected JSON including '
            'source_sha, byte-identical baseline tests, and the complete green '
            'suite. Check that existing /health, feedback and static routes are '
            'preserved. Finish with Decision: APPROVE or Decision: '
            'REQUEST_CHANGES;Reason: <specific finding>.'),
        'qa_host_port': 19433, 'container_port': 8080,
        'dockerfile': 'Dockerfile.feedback-bootstrap',
        'implementer_registry': 'pilot-backend-data.json',
        'reviewer_registry': 'pilot-techlead-reviewer.json',
    }
    validate_spec(spec, contract)
    contract_path = FOLDER / 'contract.json'
    spec_path = FOLDER / 'run.json'
    write_once(contract_path, contract)
    write_once(spec_path, spec)
    receipt = {'label': LABEL, 'base_sha': sha,
               'contract_sha256': digest(contract), 'run_spec_sha256': digest(spec),
               'contract_path': str(contract_path), 'run_spec_path': str(spec_path)}
    write_once(FOLDER / 'prepared.json', receipt)
    return receipt


if __name__ == '__main__':
    print(json.dumps(prepare(), sort_keys=True))
