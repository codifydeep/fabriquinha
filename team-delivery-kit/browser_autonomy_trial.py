"""Prepare one new, fully gated delivery on the disposable feedback application."""
import json
import argparse
from pathlib import Path
import subprocess

from evalctl import PROJECT, PRIVATE
from portable_contract import is_test_path, validate as validate_contract
from portable_run_spec import validate as validate_spec
from prepare_issue_base import verified_main
from project_selection import current
from qa_postmerge_trial import write_once
from start_eval import check_model_budget, read_model_budget

ROOT = Path(__file__).resolve().parent
BASE = '67e6fcb718ac27e42f64fd2c35f76419c999eaf6'
NEW_TEST = 'tests/test_feedback_pending_submit.py'
BROWSER_IMAGE = 'sha256:72cb1ba338b9f4047a52a8fea4702ebebebc7eb9dac11aba9c1becf605c12b4b'


def derive(template, tracked, *, label='AUTOBROWSER-1'):
    existing = set(tracked)
    if NEW_TEST in existing or 'tests/test_browser_feedback_flow.py' not in existing:
        raise ValueError('autonomous browser trial baseline drift')
    editable = {'app/static/app.js', NEW_TEST}
    files = existing | {NEW_TEST}
    tests = {name for name in existing if any(is_test_path(name, root, 'python3')
              for root in template['test_roots'])}
    contract = {**template, 'files': sorted(files), 'required_files': sorted(files),
                'editable_files': sorted(editable), 'protected_files': sorted(existing - editable),
                'test_files': sorted(tests | {NEW_TEST})}
    validate_contract(contract)
    spec = {
        'label': label,
        'title': label + ' — prevent duplicate pending submissions, autonomous browser QA',
        'description': (
            'Disposable feedback-board feature. While a valid submission POST is pending, '
            'disable the existing Submit feedback button and ignore further submit events '
            '(including programmatically dispatched form events), issuing only one POST. '
            'Re-enable the button after successful completion, HTTP failure or transport '
            'failure, allowing a subsequent attempt. Empty-title validation must not lock '
            'the form. Preserve submission messages, summary updates, completion, polling '
            'and every pre-existing test byte-for-byte. PHASE 1 TESTS ONLY: create '
            + NEW_TEST + '. Use Python unittest invoking installed Node via subprocess.run '
            'with a bounded timeout and a Node vm harness which executes the actual '
            'app/static/app.js. Inspect the existing tests/test_browser_feedback_flow.py '
            'for faithful DOM/Window.status behavior, but DO NOT edit it or import a '
            'replacement implementation. Supply a real form submit-button element through '
            'querySelector, support disabled, and hold the POST promise unresolved to assert '
            'disabled state and exactly one POST after two submitted events. Then resolve '
            'success and verify unlocked; independently cover non-OK response, rejected '
            'fetch, invalid title and a later valid resubmission. Flush promises '
            'deterministically, no sleeps/skips/swallowed exceptions. Controller captures '
            'Red and an independent profile reviews the exact new-test snapshot before '
            'implementation. PHASE 2: change ONLY app/static/app.js to pass frozen tests. '
            'Do not replay Red or edit frozen tests. Run exactly: cd /workspace && '
            'PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s . -q 2>&1. '
            'The delivery additionally requires controller-operated real Chromium QA. '
            'No network, GitHub, Docker, credentials or other projects in workers.'),
        'review_instruction': (
            'Review immutable /delivery only. Require controller Red/Green, independent '
            'new-test approval and unchanged baseline tests. Inspect behavioral coverage '
            'of pending button disabling AND duplicate event guard (one POST), unlocked '
            'state after success/HTTP failure/transport failure, invalid-title handling '
            'and subsequent valid attempt. New tests must execute actual app.js, not '
            'replacement application logic. Run the controlled full suite; never edit '
            'files or recreate Red. Real-browser acceptance is independently required by '
            'the controller before delivery. Finish with Decision: APPROVE or '
            'Decision: REQUEST_CHANGES;Reason: <specific finding>.'),
        'qa_host_port': 19439, 'container_port': 8080,
        'dockerfile': 'Dockerfile.feedback-bootstrap',
        'implementer_registry': 'pilot-frontend.json',
        'reviewer_registry': 'pilot-techlead-reviewer.json',
        'runtime_env': {'FEEDBACK_DB_PATH': '/tmp/feedback.db'},
        'browser_qa': {'scenario': 'feedback-board-pending-v1', 'browser_image': BROWSER_IMAGE}}
    validate_spec(spec, contract)
    return contract, spec


def fresh_trial(template, tracked, *, attempt=2):
    """Same product acceptance; fresh execution identity, never old task edits."""
    if attempt not in (2, 3):
        raise ValueError('unsupported autonomous browser attempt')
    contract, spec = derive(template, tracked, label='AUTOBROWSER-' + str(attempt))
    spec['qa_host_port'] = 19438 + attempt
    spec['description'] += (
        ' Keep each file within 32768 UTF-8 bytes. Use a concise reusable harness, '
        'not repeated copies for each case. In mocks, a failed POST must not '
        'insert a stored item; mutate state only on the successful response path. '
        'Assert each outcome explicitly. If a tool denies an operation, inspect '
        'the reason and adjust within scope; do not repeat the identical call.')
    if attempt == 3:
        spec['description'] += (
            ' Capture pre-submit and pending state as DISTINCT observations. Never '
            'assert opposite values of one saved snapshot. Preserve explicit polling, '
            'success message and resubmission checks in the NEW tests. Dispatch through '
            'the mocked form event target rather than calling its listener directly. '
            'On a CTO-sponsored revision, the controller seeds the prior NEW test; '
            'read that file and correct it in place without replacing the harness '
            'or dropping existing behavioral coverage. No human approval is needed '
            'to execute the assigned bounded tests-only work.')
    validate_spec(spec, contract)
    return contract, spec


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--fresh', action='store_true')
    parser.add_argument('--revision-ready', action='store_true',
                        help='new third execution with immutable-test revision seeding available')
    parser.add_argument('--prepare-only', action='store_true',
                        help='prepare definitions only; no agent dispatch or model calls')
    options = parser.parse_args()
    if options.fresh and options.revision_ready:
        parser.error('select one fresh execution identity')
    project = current()
    if PROJECT != 'delivery-kit-port2' or project['repository'] != 'codifydeep/descartavel2':
        raise ValueError('autonomy trial restricted to disposable project')
    budget = read_model_budget() if options.prepare_only else check_model_budget()
    if not options.prepare_only and budget['remaining'] < 128:
        raise ValueError('autonomy trial requires 128 available calls')
    if verified_main() != BASE:
        raise ValueError('autonomy trial base changed; replan required')
    tracked = subprocess.check_output(['git', '-C', str(project['checkout']),
        'ls-tree', '-r', '--name-only', BASE], text=True).splitlines()
    template = json.loads((ROOT / 'projects/descartavel2-browser-recovery.contract.json').read_text())
    contract, spec = (fresh_trial(template, tracked, attempt=3) if options.revision_ready else
                      fresh_trial(template, tracked) if options.fresh else derive(template, tracked))
    suffix = '-3' if options.revision_ready else '-2' if options.fresh else ''
    write_once(ROOT / ('projects/descartavel2-browser-autonomy' + suffix + '.contract.json'), contract)
    write_once(ROOT / ('projects/descartavel2-browser-autonomy' + suffix + '.run.json'), spec)
    write_once(PRIVATE / ('browser-autonomy' + suffix + '-intake.json'), {
        'base_sha': BASE, 'label': spec['label'], 'status': 'prepared',
        'model_call_ceiling': budget['max_calls'], 'remaining_at_intake': budget['remaining']})
    print(json.dumps({'label': spec['label'], 'base_sha': BASE, 'status': 'prepared'}))


if __name__ == '__main__':
    main()
