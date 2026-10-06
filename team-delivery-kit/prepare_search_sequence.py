"""Pin a fresh two-card integration trial; generate contracts, never product code."""
import json
from pathlib import Path
import subprocess

from portable_contract import is_test_path, validate as validate_contract
from portable_run_spec import validate as validate_spec
from dependent_sequence import load_plan
from generate_dependent_contract import save_generated

ROOT = Path(__file__).resolve().parent
BASE = '6492437ca62617b5081e0c71b8e5431bc4827099'
PREFIX = 'descartavel2-search-1'


def derive(tracked, template):
    existing = set(tracked)
    api_test = 'tests/test_feedback_search_api.py'
    ui_test = 'tests/test_feedback_search_client.py'
    if {api_test, ui_test} & existing:
        raise ValueError('search trial is not fresh')
    baseline_tests = {p for p in existing if is_test_path(p, '.', 'python3')}
    if 'tests/test_feedback_sort_client.py' not in baseline_tests:
        raise ValueError('delivered sort baseline required')
    artifacts = {}
    previous = set(existing)
    review = ('Review frozen /delivery only. Preserve all baseline tests byte-for-byte. '
        'Require genuine controller Red, independent test approval and full Green. '
        'Read real implementation and new test completely. No generic terminal or '
        'Python, edits, Red recreation or administration. Run ONLY '
        'cd /delivery && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s . -q 2>&1. '
        'Finish with one standalone line Decision: APPROVE or '
        'Decision: REQUEST_CHANGES;Reason: <specific finding>. ')
    requirements = [
        'Extend GET /feedback with optional q title-substring search. Trim q and '
        'match title using Unicode casefold. Absent or whitespace-only q is exactly '
        'compatible with the existing unsearched response. Match title only, not '
        'description. Compose with existing status filter and preserve its invalid '
        'status errors. Preserve item order, envelope, create/complete responses and '
        '/feedback/summary whole-board counts (summary ignores q). Parameter data '
        'must never be interpolated into SQL. Tests must exercise actual HTTP '
        'behavior, including case, whitespace, nonmatch, description-only text, '
        'Unicode, q+status and default compatibility. No frontend changes.',
        'Consume predecessor search API with a native input type=search accessible '
        'name Search feedback, outside the create-feedback form. Enter in this '
        'input applies its query without submitting or changing the create form. '
        'Default query empty; trim whitespace. Omit q for blank. Preserve existing '
        'status and numeric sort controls. Search composes with both. Each browser '
        'has independent query in page memory only. Query survives polling and '
        'creation/completion. Discard stale fetch responses from earlier query, '
        'status or request generation. Empty search shows a clear message; clearing '
        'restores all matching current-status rows. Whole-board summary stays '
        'unchanged. Preserve typed drafts, pending guard, Escape and accessibility. '
        'Use actual app.js with faithful DOM/Node harness, not source regex or '
        'replacement business logic. Do not change backend or predecessor tests.'
    ]
    for index, (role, label, new_test, code) in enumerate([
        ('api', 'SEARCHAPI-1', api_test, {'app/server.py', 'app/store.py'}),
        ('ui', 'SEARCHUI-1', ui_test, {'app/static/app.js', 'app/static/index.html'})]):
        editable = code | {new_test}
        contract = {**template, 'files': sorted(previous | editable),
                    'required_files': sorted(previous | {new_test}),
                    'editable_files': sorted(editable),
                    'protected_files': sorted(previous - code),
                    'test_files': sorted(baseline_tests | {api_test} | ({ui_test} if index else set()))}
        validate_contract(contract)
        description = ('Fresh dependency qualification on disposable feedback board. '
            + requirements[index] + ' PHASE1 tests only: add ' + new_test +
            ' (max32768 UTF-8 bytes); preserve all existing tests byte-for-byte. '
            'Controller captures Red and independent immutable test review. PHASE2 '
            'edit only declared product files; never edit approved tests or recreate '
            'Red. Run cd /workspace && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest '
            'discover -s . -q 2>&1. No GitHub, Docker, network, credentials or '
            'administrative tools. Completion requires independent delivery review, '
            'CI, local deployment and fixed real-browser QA on exact merged SHA.')
        spec = {'label': label, 'title': label + ' — dependent title search ' + role,
                'description': description, 'review_instruction': review + requirements[index],
                'qa_host_port': 19447 + index, 'container_port': 8080,
                'dockerfile': 'Dockerfile.feedback-bootstrap',
                'implementer_registry': 'pilot-backend-data.json' if index == 0 else 'pilot-frontend.json',
                'reviewer_registry': 'pilot-techlead-reviewer.json',
                'runtime_env': {'FEEDBACK_DB_PATH': '/tmp/feedback.db'},
                'browser_qa': {'browser_image': 'sha256:72cb1ba338b9f4047a52a8fea4702ebebebc7eb9dac11aba9c1becf605c12b4b',
                    'scenario': 'feedback-board-search-api-v1' if index == 0 else 'feedback-board-search-v1'}}
        validate_spec(spec, contract)
        artifacts[PREFIX + '-' + role + '.contract.json'] = contract
        artifacts[PREFIX + '-' + role + '.run.json'] = spec
        previous |= {new_test}
    artifacts[PREFIX + '.sequence.json'] = {
        'sequence': 'SEARCH-1-DELIVERY', 'project_config': 'descartavel2.json',
        'stages': [{'contract': PREFIX + '-api.contract.json',
                    'run_spec': PREFIX + '-api.run.json', 'depends_on': None},
                   {'contract': PREFIX + '-ui.contract.json',
                    'run_spec': PREFIX + '-ui.run.json', 'depends_on': 'SEARCHAPI-1'}]}
    return artifacts


def main():
    from evalctl import PROJECT
    from project_selection import current
    from prepare_issue_base import verified_main
    selected = current()
    if PROJECT != 'delivery-kit-port2' or selected['repository'] != 'codifydeep/descartavel2':
        raise ValueError('isolated disposable project only')
    if verified_main() != BASE:
        raise ValueError('trial base moved; replan required')
    tracked = subprocess.check_output(['git', '-C', str(selected['checkout']),
        'ls-tree', '-r', '--name-only', BASE], text=True).splitlines()
    template = json.loads((ROOT / 'projects/descartavel2-sort-1.contract.json').read_text())
    artifacts = derive(tracked, template)
    for name, value in artifacts.items():
        save_generated(ROOT / 'projects' / name, value)
    plan = load_plan(ROOT / 'projects' / (PREFIX + '.sequence.json'))
    print(json.dumps({'stage': 'prepared_not_dispatched', 'base_sha': BASE,
                      'sequence': plan['name'], 'plan_sha256': plan['sha256']}))


if __name__ == '__main__':
    main()
