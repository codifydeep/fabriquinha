"""Pin a real accessibility increment without changing the delivered baseline."""
import json
import subprocess
from pathlib import Path

from browser_autonomy_trial import BROWSER_IMAGE
from evalctl import PROJECT, PRIVATE
from portable_contract import is_test_path, validate as validate_contract
from portable_run_spec import validate as validate_spec
from prepare_issue_base import verified_main
from project_selection import current
from qa_postmerge_trial import write_once
from start_eval import read_model_budget

ROOT = Path(__file__).resolve().parent
BASE = '8fdedd8df2e819f2ef2a8ce5fedb549e2bda8c65'
NEW_TEST = 'tests/test_feedback_busy_accessibility.py'


def derive(template, tracked):
    existing = set(tracked)
    if NEW_TEST in existing or 'tests/test_feedback_pending_submit.py' not in existing:
        raise ValueError('accessible feedback baseline drift')
    editable = {'app/static/app.js', NEW_TEST}
    files = existing | {NEW_TEST}
    tests = {name for name in existing if any(is_test_path(name, root, 'python3')
              for root in template['test_roots'])}
    contract = {**template, 'files': sorted(files), 'required_files': sorted(files),
                'editable_files': sorted(editable), 'protected_files': sorted(existing - editable),
                'test_files': sorted(tests | {NEW_TEST})}
    validate_contract(contract)
    spec = {
        'label': 'ACCESSIBLE-1',
        'title': 'ACCESSIBLE-1 — accessible feedback pending state, autonomous delivery',
        'description': (
            'Real increment on the delivered disposable feedback board. Announce form '
            'pending state for assistive technology: #feedback-form must expose the '
            'aria-busy attribute as the string false initially, true while a valid POST '
            'is unresolved, and false after success, non-OK HTTP response or rejected '
            'fetch. A later valid retry must announce true again. Whitespace-only title '
            'validation must leave false and issue no POST. Preserve button disabling, '
            'duplicate event suppression, messages, summary, completion and polling. '
            'Preserve ALL 128 baseline tests byte-for-byte. PHASE 1 TESTS ONLY: create '
            + NEW_TEST + '. Use Python unittest and bounded subprocess Node vm running '
            'the actual app/static/app.js. You may import NODE_HARNESS_TEMPLATE from '
            'tests/test_feedback_pending_submit.py and extend only its observation '
            'snapshot to report the form attribute; never transform the app source or '
            'edit the imported baseline test. Read its helper/driver before reuse. '
            'Capture distinct initial/pending/settled observations, support real '
            'setAttribute/getAttribute semantics, hold POST promises, flush microtasks '
            'deterministically, exercise success/HTTP failure/transport failure/empty '
            'title/retry. No sleeps, skips or swallowed harness errors. Keep each file '
            'within 32768 bytes. Controller captures Red and independent test review. '
            'PHASE 2: change ONLY app/static/app.js to satisfy frozen tests. Never '
            'recreate Red or edit frozen tests. Full suite exactly: cd /workspace && '
            'PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s . -q 2>&1. '
            'Controller owns PR, independent review, CI, deployment and real Chromium '
            'acceptance. No GitHub/Docker/network/credentials/other projects in workers. '
            'Denied calls require adjustment, not identical retries.'),
        'review_instruction': (
            'Immutable /delivery review only. Read actual files and inspect historical '
            'controller Red/Green and independent new-test approval. All prior tests '
            'including pending-submit tests must remain unchanged. Require aria-busy '
            'false initially, true during unresolved valid POST, false after success, '
            'HTTP failure and transport failure, true again on valid retry; empty title '
            'stays false without POST. Tests must execute actual JS, not replacement '
            'logic. No Python tool, patches, general terminal, file writes or Red '
            'reproduction. Run ONLY registered full suite: cd /delivery && '
            'PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s . -q 2>&1. '
            'Controller separately requires real browser acceptance. Finish with '
            'Decision: APPROVE or Decision: REQUEST_CHANGES;Reason: <specific finding>.'),
        'qa_host_port': 19442, 'container_port': 8080,
        'dockerfile': 'Dockerfile.feedback-bootstrap',
        'implementer_registry': 'pilot-frontend.json',
        'reviewer_registry': 'pilot-techlead-reviewer.json',
        'runtime_env': {'FEEDBACK_DB_PATH': '/tmp/feedback.db'},
        'browser_qa': {'scenario': 'feedback-board-pending-accessibility-v1',
                       'browser_image': BROWSER_IMAGE}}
    validate_spec(spec, contract)
    return contract, spec


def main():
    project = current()
    if PROJECT != 'delivery-kit-port2' or project['repository'] != 'codifydeep/descartavel2':
        raise ValueError('accessible trial restricted to disposable project')
    budget = read_model_budget()
    if budget['remaining'] < 128:
        raise ValueError('accessible trial requires 128 available calls')
    if verified_main() != BASE:
        raise ValueError('accessible trial base changed; replan required')
    tracked = subprocess.check_output(['git', '-C', str(project['checkout']),
        'ls-tree', '-r', '--name-only', BASE], text=True).splitlines()
    template = json.loads((ROOT / 'projects/descartavel2-browser-autonomy-3.contract.json').read_text())
    contract, spec = derive(template, tracked)
    write_once(ROOT / 'projects/descartavel2-accessible-1.contract.json', contract)
    write_once(ROOT / 'projects/descartavel2-accessible-1.run.json', spec)
    write_once(PRIVATE / 'accessible-1-intake.json', {
        'base_sha': BASE, 'label': spec['label'], 'status': 'prepared',
        'model_call_ceiling': budget['max_calls'], 'remaining_at_intake': budget['remaining']})
    print(json.dumps({'label': spec['label'], 'base_sha': BASE, 'status': 'prepared'}))


if __name__ == '__main__':
    main()
