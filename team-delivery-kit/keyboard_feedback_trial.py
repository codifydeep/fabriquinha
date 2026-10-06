"""Small real keyboard UX increment to qualify the offline review RPC."""
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
BASE = 'f9c0cd865535a2f8d48cd7b439fb3b87e7464f35'
NEW_TEST = 'tests/test_feedback_keyboard_dismiss.py'


def derive(template, tracked):
    existing = set(tracked)
    if NEW_TEST in existing or 'tests/test_feedback_busy_accessibility.py' not in existing:
        raise ValueError('keyboard feedback baseline drift')
    editable = {'app/static/app.js', NEW_TEST}
    files = existing | {NEW_TEST}
    tests = {name for name in existing if any(is_test_path(name, root, 'python3')
              for root in template['test_roots'])}
    contract = {**template, 'files': sorted(files), 'required_files': sorted(files),
                'editable_files': sorted(editable), 'protected_files': sorted(existing - editable),
                'test_files': sorted(tests | {NEW_TEST})}
    validate_contract(contract)
    spec = {
        'label': 'KEYBOARD-1', 'title': 'KEYBOARD-1 — dismiss form status with Escape, isolated review',
        'description': (
            'Real keyboard-accessibility increment on the delivered feedback board. '
            'When a keydown event with key Escape bubbles to #feedback-form and no '
            'submission is pending, dismiss the current #form-status message and '
            'remove its is-error class. Preserve typed title/description, board, '
            'summary, focus, button availability and aria-busy=false; do not submit, '
            'reload or clear the form. Escape while a valid POST is unresolved must '
            'NOT dismiss Submitting..., cancel the POST, unlock the button or clear '
            'aria-busy=true. Other keys must not dismiss messages. Repeated Escape '
            'with an empty status must be harmless. After an error, dismissal must '
            'still allow a later valid submission. Preserve all 138 baseline tests '
            'byte-for-byte, including busy-accessibility and pending-submit tests. '
            'PHASE 1 TESTS ONLY: create ' + NEW_TEST + '. Use Python unittest and '
            'bounded subprocess Node vm that executes actual app/static/app.js. '
            'You may import the baseline NODE_HARNESS_TEMPLATE from '
            'tests/test_feedback_pending_submit.py and extend its observations '
            'and driver additively; never transform app source or edit baseline '
            'tests. Read the existing harness before reuse. Dispatch keydown '
            'through the form event target with realistic key values; retain '
            'real classList state and attribute semantics. Test idle validation '
            'and HTTP/transport errors, unrelated keys, draft preservation, '
            'held pending POST, repeated dismissal and later successful retry. '
            'Use distinct observations, deterministic promise flushing, no sleeps, '
            'skips or swallowed exceptions; files must stay under 32768 bytes. '
            'Controller captures Red; independent profile reviews new tests before '
            'PHASE 2, which may change ONLY app/static/app.js. Never change frozen '
            'tests or recreate Red. Run exactly: cd /workspace && '
            'PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s . -q 2>&1. '
            'Controller owns PR, CI, deployment and real browser QA. No GitHub, '
            'Docker, credentials, network or other projects in workers.'),
        'review_instruction': (
            'Immutable /delivery only; inspect actual files, historical Red/Green '
            'and independent new-test approval. All 138 prior tests stay unchanged. '
            'Require real-JS behavioral tests of Escape dismissing idle error '
            'text/class without losing draft or submitting; other keys unchanged; '
            'held pending POST retains status/button/busy and is not cancelled; '
            'repeated dismissal harmless and later valid submission succeeds. '
            'No Python tool, probes, patches, general terminal or Red reproduction. '
            'Run ONLY registered full suite: cd /delivery && '
            'PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s . -q 2>&1. '
            'That operation calls the controller offline Docker runner; never '
            'fall back to local execution. Approval requires the controller receipt '
            'for this review and manifest. Browser QA is separately required. '
            'Finish with Decision: APPROVE or '
            'Decision: REQUEST_CHANGES;Reason: <specific finding>.'),
        'qa_host_port': 19443, 'container_port': 8080,
        'dockerfile': 'Dockerfile.feedback-bootstrap',
        'implementer_registry': 'pilot-frontend.json',
        'reviewer_registry': 'pilot-techlead-reviewer.json',
        'runtime_env': {'FEEDBACK_DB_PATH': '/tmp/feedback.db'},
        'browser_qa': {'scenario': 'feedback-board-keyboard-dismiss-v1', 'browser_image': BROWSER_IMAGE}}
    validate_spec(spec, contract)
    return contract, spec


def main():
    project = current()
    if PROJECT != 'delivery-kit-port2' or project['repository'] != 'codifydeep/descartavel2':
        raise ValueError('keyboard trial restricted to disposable project')
    budget = read_model_budget()
    if budget['remaining'] < 128:
        raise ValueError('keyboard trial requires 128 available calls')
    if verified_main() != BASE:
        raise ValueError('keyboard trial base changed; replan required')
    tracked = subprocess.check_output(['git', '-C', str(project['checkout']),
        'ls-tree', '-r', '--name-only', BASE], text=True).splitlines()
    template = json.loads((ROOT / 'projects/descartavel2-accessible-1.contract.json').read_text())
    contract, spec = derive(template, tracked)
    write_once(ROOT / 'projects/descartavel2-keyboard-1.contract.json', contract)
    write_once(ROOT / 'projects/descartavel2-keyboard-1.run.json', spec)
    write_once(PRIVATE / 'keyboard-1-intake.json', {
        'base_sha': BASE, 'label': spec['label'], 'status': 'prepared',
        'model_call_ceiling': budget['max_calls'], 'remaining_at_intake': budget['remaining']})
    print(json.dumps({'label':spec['label'],'base_sha':BASE,'status':'prepared'}))


if __name__ == '__main__':
    main()
