"""Prepare the evidence-backed browser repair without modifying product code."""
import json
from pathlib import Path
import subprocess

from evalctl import PRIVATE, PROJECT
from portable_contract import is_test_path, validate as validate_contract
from portable_run_spec import validate as validate_spec
from prepare_issue_base import verified_main
from project_selection import current
from qa_postmerge_trial import write_once

ROOT = Path(__file__).resolve().parent
BASE = 'eeb0718643e35a3ecb58f1b44711df928225950d'
NEW_TEST = 'tests/test_browser_feedback_flow.py'


def derive(template, tracked):
    existing = set(tracked)
    if NEW_TEST in existing or not {'app/static/app.js', 'tests/test_feedback_summary_ui.py'} <= existing:
        raise ValueError('browser recovery baseline drift')
    tests = {name for name in existing if any(
        is_test_path(name, root, template['test_command'][0])
        for root in template['test_roots'])}
    editable = {'app/static/app.js', NEW_TEST}
    files = existing | {NEW_TEST}
    contract = {**template, 'files': sorted(files), 'required_files': sorted(files),
                'editable_files': sorted(editable),
                'protected_files': sorted(existing - editable),
                'test_files': sorted(tests | {NEW_TEST})}
    validate_contract(contract)
    spec = {
        'label': 'BROWSERFIX-1',
        'title': 'BROWSERFIX-1 — executable client regression and feedback form repair',
        'description': (
            'Repair EVAL-65 on exact base ' + BASE + '. Real browser submission fails '
            'in setStatus: Cannot read properties of undefined (reading toggle). '
            'app.js declares top-level var status, which collides with the native '
            'string-valued Window.status property. Do not edit any old test. '
            'PHASE 1 TESTS ONLY: create ' + NEW_TEST + ', a Python unittest invoking '
            'the installed Node with subprocess.run and a bounded timeout. Embed '
            'a Node vm harness which loads and EXECUTES the real app/static/app.js, '
            'not a replacement implementation. Provide minimal DOM elements, event '
            'listeners, fake fetch returning stateful feedback/summary responses, '
            'and captured interval callbacks. Emulate Window.status as a string '
            'accessor (setter coerces to String) BEFORE executing the classic script. '
            'Assert the form submit handler actually issues POST /feedback, completion '
            'issues its API request, summary counts refresh after creation/completion, '
            'and a captured poll refreshes externally changed state. Flush promises '
            'deterministically; no wall-clock sleeps, missing-Node skip, swallowed '
            'exceptions or regex-only assertions. The harness is a controlled JS '
            'unit test, NOT proof of a real browser or network. It must genuinely fail '
            'on the current base. Controller captures Red. PHASE 2: edit only '
            'app/static/app.js to fix the collision while preserving all frozen '
            'tests, including their initial loadSummary call assertion. Do not '
            'weaken tests or recreate Red. Run exactly: cd /workspace && '
            'PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s . -q 2>&1. '
            'No GitHub, network, Docker, credentials or other projects.'),
        'review_instruction': (
            'Review immutable /delivery only. Require controller Red/Green and '
            'byte-identical old tests. Inspect the NEW Node VM regression: real '
            'client is executed with native Window.status coercion; submit, '
            'completion and polling have behavioral assertions and no skips. '
            'Reject mocked replacement app logic, swallowed exceptions, or mere '
            'source-text assertions. Run controlled full suite. Do not edit/replay '
            'Red. This is not real-browser acceptance. Finish with Decision: '
            'APPROVE or Decision: REQUEST_CHANGES;Reason: <specific finding>.'),
        'qa_host_port': 19437, 'container_port': 8080,
        'dockerfile': 'Dockerfile.feedback-bootstrap',
        'implementer_registry': 'pilot-frontend.json',
        'reviewer_registry': 'pilot-techlead-reviewer.json',
        'runtime_env': {'FEEDBACK_DB_PATH': '/tmp/feedback.db'},
    }
    validate_spec(spec, contract)
    return contract, spec


def main():
    project = current()
    if PROJECT != 'delivery-kit-port2' or project['repository'] != 'codifydeep/descartavel2':
        raise ValueError('browser recovery restricted to isolated disposable project')
    if verified_main() != BASE:
        raise ValueError('main moved; browser recovery requires replan')
    tracked = subprocess.check_output(['git', '-C', str(project['checkout']),
                                      'ls-tree', '-r', '--name-only', BASE], text=True).splitlines()
    template = json.loads((ROOT / 'projects/descartavel2-summary-slice-v2-ui.contract.json').read_text())
    contract, spec = derive(template, tracked)
    folder = ROOT / 'projects'
    write_once(folder / 'descartavel2-browser-recovery.contract.json', contract)
    write_once(folder / 'descartavel2-browser-recovery.run.json', spec)
    write_once(PRIVATE / 'browser-recovery-intake.json', {
        'base_sha': BASE, 'incident_issue': '01a0f44a-10b1-7cb9-a9a2-f1d418820da9',
        'parent_issue': '01a0f37b-e6c4-74f2-a6cf-45d946a069bf',
        'label': spec['label'], 'status': 'prepared_not_browser_approved'})
    print(json.dumps({'label': spec['label'], 'base_sha': BASE, 'status': 'prepared'}))


if __name__ == '__main__':
    main()
