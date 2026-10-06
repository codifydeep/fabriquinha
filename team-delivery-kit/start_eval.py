"""One controlled issue: create unassigned, pin Git base, arm review, assign."""
import argparse
import json
import subprocess

from bootstrap_multica import PRIVATE
from prepare_issue_base import broker_post, prepare, verified_main
from review_wakeup import ensure_review_wakeup
from evalctl import PROJECT

TITLE = 'current-main cube feature with base-aware review'
DESCRIPTION = (
    'Disposable calculator only. Implement cube(value) in calc.py using '
    'Red-Green-Refactor. Initially add only test_cube_positive for 3 -> 27. '
    'Run Red, Green and the complete suite. Preserve every existing test '
    'unchanged. This initial delivery is intentionally '
    'incomplete: final acceptance REQUIRES a separate test_cube_negative for '
    '-2 -> -8. The independent reviewer must request that change before '
    'approval; a green positive-only suite is not sufficient. No product '
    'repository, network or credentials.'
)
FEATURES = {
    'cube': {
        'title': TITLE, 'description': DESCRIPTION,
        'required_tests': ['test_cube_negative'],
        'review_instruction': (
            'Review only the frozen /delivery for cube(value). Preserve all '
            'preexisting tests. Run the full suite. Require a separate '
            'test_cube_negative for -2 -> -8; if missing, request changes '
            'with that exact finding. Do not edit files. Finish with '
            'Decision: APPROVE or Decision: REQUEST_CHANGES and evidence.')},
    'negate': {
        'title': 'current-main negate feature with base-aware review',
        'description': (
            'Disposable calculator only. Implement negate(value) in calc.py '
            'using Red-Green-Refactor. Initially add only test_negate_positive '
            'for 3 -> -3. Run Red, Green and the complete suite. Preserve every '
            'existing test unchanged. Initial '
            'delivery is intentionally incomplete: final acceptance REQUIRES '
            'a separate test_negate_negative for -2 -> 2. The independent '
            'reviewer must request that change before approval. No product '
            'repository, network or credentials.'),
        'required_tests': ['test_negate_negative'],
        'review_instruction': (
            'Review only frozen /delivery for negate(value). Preserve all '
            'preexisting tests. Run exactly: cd /delivery && '
            'PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -q 2>&1. '
            'Include the terminal receipt showing Ran N tests and OK; do not '
            'pipe through tail or add pytest. Require a separate '
            'test_negate_negative for -2 -> 2. If missing, request that exact '
            'change. Do not edit files. Finish with Decision: APPROVE or '
            'Decision: REQUEST_CHANGES and evidence.')},
    'absolute': {
        'title': 'current-main absolute feature with base-aware review',
        'description': (
            'Disposable calculator only. Implement absolute(value) in calc.py '
            'using Red-Green-Refactor. Initially add only test_absolute_positive '
            'for 3 -> 3. Run Red, Green and the complete suite. Preserve every '
            'existing test unchanged. Initial delivery is intentionally incomplete: '
            'final acceptance REQUIRES a separate test_absolute_negative for '
            '-2 -> 2. The independent reviewer must request that change before '
            'approval. No product repository, network or credentials.'),
        'required_tests': ['test_absolute_negative'],
        'review_instruction': (
            'Review only frozen /delivery for absolute(value). Preserve all '
            'preexisting tests and run the complete suite. Require a separate '
            'test_absolute_negative for -2 -> 2. If missing, request that exact '
            'change. Do not edit files. Finish with exactly one line '
            'Decision: APPROVE or Decision: REQUEST_CHANGES and evidence.')},
    'double': {
        'title': 'current-main double feature with base-aware review',
        'description': (
            'Disposable calculator only. Implement double(value) in calc.py '
            'using Red-Green-Refactor. Initially add only test_double_positive '
            'for 3 -> 6. Run Red, Green and the complete suite. Preserve every '
            'existing test unchanged. Initial delivery is intentionally incomplete: '
            'final acceptance REQUIRES a separate test_double_negative for '
            '-2 -> -4. The independent reviewer must request that change before '
            'approval. No product repository, network or credentials.'),
        'required_tests': ['test_double_negative'],
        'review_instruction': (
            'Review only frozen /delivery for double(value). Preserve all '
            'preexisting tests and run the complete suite. Require a separate '
            'test_double_negative for -2 -> -4. If missing, request that exact '
            'change. Do not edit files. Finish with exactly one line '
            'Decision: APPROVE or Decision: REQUEST_CHANGES and evidence.')},
}

MIN_MODEL_CALLS_FOR_NEW_RELEASE = 32


def read_model_budget():
    raw = subprocess.check_output(
        ['docker', 'exec', PROJECT + '-model-proxy-1', 'python3', '-c',
         'import urllib.request; print(urllib.request.urlopen('
         '"http://127.0.0.1:8080/status", timeout=3).read().decode())'], text=True)
    status = json.loads(raw)
    if set(status) != {'calls', 'max_calls', 'remaining'} or any(
            type(status[key]) is not int or status[key] < 0 for key in status):
        raise ValueError('invalid model budget receipt')
    if status['calls'] + status['remaining'] != status['max_calls']:
        raise ValueError('inconsistent model budget receipt')
    return status


def check_model_budget():
    status = read_model_budget()
    if status['remaining'] < MIN_MODEL_CALLS_FOR_NEW_RELEASE:
        raise ValueError('model budget too low to start a release')
    return status


def cli(*args):
    raw = subprocess.check_output(['docker', 'exec', PROJECT + '-runtime-1',
                                   'multica', 'issue', *args, '--output', 'json'], text=True)
    return json.loads(raw)


def issue(title, description):
    matches = [item for item in cli('list')['issues'] if item['title'] == title]
    if len(matches) > 1:
        raise ValueError('duplicate evaluation issue')
    if matches:
        current = matches[0]
        if current['description'] != description:
            raise ValueError('existing evaluation issue changed')
        return current
    check_model_budget()
    return cli('create', '--title', title, '--description', description, '--status', 'todo')


def ensure_started(label, feature):
    if feature not in FEATURES:
        raise ValueError('unsupported fixed evaluation feature')
    settings = FEATURES[feature]
    title = label + ' — ' + settings['title']
    registry = json.loads((PRIVATE / 'implementer.json').read_text())
    reviewer = json.loads((PRIVATE / 'reviewer.json').read_text())
    if registry['workspace_id'] != reviewer['workspace_id']:
        raise ValueError('agent workspace mismatch')
    current = issue(title, settings['description'])
    if current.get('assignee_id') not in (None, registry['agent_id']):
        raise ValueError('unexpected existing assignee')
    if current.get('assignee_id') == registry['agent_id']:
        query = ('import sqlite3,json,sys; '
                 'c=sqlite3.connect("file:/broker-state/leases.sqlite?mode=ro",uri=True); '
                 'r=c.execute("SELECT base_sha FROM issue_bases WHERE issue_id=?",'
                 '(sys.argv[1],)).fetchone(); print(json.dumps(r[0] if r else None))')
        base = json.loads(subprocess.check_output(
            ['docker', 'exec', PROJECT + '-execution-broker-1', 'python', '-c',
             query, current['id']], text=True))
        if not base:
            raise ValueError('assigned issue has no registered base')
        return {'issue_id': current['id'], 'identifier': current.get('identifier'),
                'base_sha': base, 'assigned': True}
    check_model_budget()
    pinned = prepare(current['id'])
    broker_post('/v1/issue-requirements',
                {'issue_id': current['id'], 'required_tests': settings['required_tests']})
    if verified_main() != pinned['base_sha']:
        raise ValueError('main moved before assignment')
    ensure_review_wakeup(cli, current['id'], registry['agent_id'],
                         reviewer['agent_id'], settings['review_instruction'])
    if verified_main() != pinned['base_sha']:
        raise ValueError('main moved before dispatch')
    if current.get('assignee_id') is None:
        assigned = cli('assign', current['id'], '--to-id', registry['agent_id'])
        if assigned.get('assignee_id') != registry['agent_id']:
            raise ValueError('assignment not confirmed')
    return {'issue_id': current['id'], 'identifier': current.get('identifier'),
            'base_sha': pinned['base_sha'], 'assigned': True}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--label', required=True)
    parser.add_argument('--feature', choices=sorted(FEATURES), default='cube')
    args = parser.parse_args()
    if not args.label.startswith('EVAL-') or not args.label[5:].isdigit():
        raise ValueError('expected evaluation label EVAL-N')
    print(json.dumps(ensure_started(args.label, args.feature)))


if __name__ == '__main__':
    main()
