"""Ask the enrolled Tech Lead for a bounded C2 contract correction."""
import hashlib
import json
import re
import subprocess

from bootstrap_multica import BACKEND_PORT, PRIVATE
from evalctl import PROJECT
from planning_intake import completed_output, safe_path, short
from prepare_issue_base import verified_main
from project_selection import current as selected_project
from release_eval import save_receipt
from start_eval import cli
from stdlib_replan import RUN


LEDGER = PRIVATE / 'dependent-replans' / (RUN + '-C2.json')
ISSUE = '01a0eea3-5842-7632-81dc-5bb00b63db78'
C1 = '01a0eea3-564f-747a-9c00-4134847c21ef'
COMMAND = ['python3', '-m', 'unittest', 'discover', '-s', '.', '-q']
REQUIRED = {'app/server.py', 'app/static/index.html', 'app/static/app.js',
            'app/static/style.css', 'tests/test_board_ui.py'}


def parse(text, original, protected_tests=()):
    if not isinstance(text, str) or len(text) > 5000:
        raise ValueError('bounded C2 decision required')
    candidate = text.strip()
    fence = re.fullmatch(r'```(?:json)?\s*\n(.*?)\n```', candidate,
                         re.IGNORECASE | re.DOTALL)
    if fence:
        candidate = fence.group(1).strip()
    result = json.loads(candidate)
    if not isinstance(result, dict) or set(result) != {'role', 'decision', 'files', 'rationale'}:
        raise ValueError('C2 decision fields invalid')
    files = result['files']
    if (result['role'] != 'techlead' or result['decision'] != 'serve_static_from_existing_server'
            or not isinstance(files, list) or len(files) > 12 or len(files) != len(set(files))
            or not all(safe_path(name) for name in files)
            or not REQUIRED <= set(files)
            or not set(original['files']) <= set(files)
            or bool(set(files) & set(protected_tests))
            or any(name not in REQUIRED and not (
                name.startswith('app/static/') or
                (name.startswith('tests/test_') and name.endswith('.py')))
                for name in files)
            or not short(result['rationale'], 3000)):
        raise ValueError('C2 decision does not preserve the planned product scope')
    acceptance = list(original['acceptance']) + [
        'Red first: a new test fails until GET / and the named static assets are served '
        'by app/server.py with correct content types; traversal outside app/static is rejected.',
        'Green: the deployed app/server.py serves the same-origin UI at /, and every '
        'existing API endpoint and protected regression test remains unchanged and passing.',
    ]
    card = {**original, 'files': sorted(files), 'required_files': sorted(set(files)),
            'acceptance': acceptance}
    if card['id'] != 'C2' or card['owner'] != 'frontend' or card['depends_on'] != ['C1'] \
            or card['test_command'] != COMMAND:
        raise ValueError('C2 card identity or dependency changed')
    return card


def main():
    if PROJECT != 'delivery-kit-port2' or BACKEND_PORT != '19081':
        raise ValueError('C2 replan is isolated to port2')
    plan = json.loads((PRIVATE / 'replans' / (RUN + '.json')).read_text())
    planned = json.loads((PRIVATE / 'planned-cards' / (RUN + '.json')).read_text())
    c1 = json.loads((PRIVATE / 'release-receipts' / 'FB-1.json').read_text())
    original = next(card for card in plan['proposal']['cards'] if card['id'] == 'C2')
    if (plan['stage'] != 'plan_ready' or planned['cards']['C2'] != ISSUE
            or planned['cards']['C1'] != C1 or c1['stage'] != 'deployed_qa_passed'
            or c1['issue_id'] != C1 or c1['merge_sha'] != verified_main()
            or cli('get', C1)['status'] != 'done'):
        raise ValueError('C1 publication and C2 dependency not verified')
    c2 = cli('get', ISSUE)
    meta = cli('metadata', 'list', ISSUE)
    if (c2['status'] != 'blocked' or c2.get('assignee_id') is not None
            or meta.get('execution_gate') != 'awaiting_generated_contract'
            or meta.get('planning_sha256') != planned['plan_sha256']):
        raise ValueError('C2 no longer in planned blocked state')
    instruction = (
        'You are the Tech Lead correcting only the C2 technical file contract. '
        'C1 was delivered and QA passed at main SHA ' + c1['merge_sha'] + '. '
        'The current app/server.py serves /health and /feedback but no static UI. '
        'C2 acceptance requires a same-origin served board UI; the existing C2 '
        'file list omitted app/server.py. Preserve the original C2 product scope, '
        'all existing tests and the local Python-stdlib architecture. The '
        'implementation must add app/server.py to its edit allowlist, with a new '
        'test covering GET /, content types and path traversal. Decide and return '
        'one JSON object only: {"role":"techlead",'
        '"decision":"serve_static_from_existing_server",'
        '"files":["app/server.py","app/static/index.html","app/static/app.js",'
        '"app/static/style.css","tests/test_board_ui.py"],"rationale":"..."}. '
        'You may add other NEW code or test paths only if necessary; never edit '
        'a pre-existing test. Do not claim to have changed code or ask the CEO. '
        'Original C2 acceptance: ' + json.dumps(original['acceptance'], ensure_ascii=False))
    digest = hashlib.sha256(instruction.encode()).hexdigest()
    title = RUN + ' — C2 technical contract correction'
    existing = json.loads(LEDGER.read_text()) if LEDGER.exists() else None
    if existing and existing.get('stage') == 'decision_validated':
        if existing['context_sha256'] != digest or existing['base_sha'] != c1['merge_sha']:
            raise ValueError('C2 replan receipt drift')
        print(json.dumps(existing, sort_keys=True))
        return 0
    matches = [x for x in cli('list')['issues'] if x['title'] == title]
    if len(matches) > 1:
        raise ValueError('duplicate C2 planning issue')
    issue = matches[0] if matches else cli('create', '--title', title,
                                          '--description', instruction, '--status', 'todo')
    if issue['description'] != instruction:
        raise ValueError('C2 planning instruction drift')
    lead = json.loads((PRIVATE / 'planning-agents.json').read_text())['agents']['techlead']
    if issue.get('assignee_id') not in (None, lead):
        raise ValueError('C2 planning owner drift')
    receipt = existing or {'stage': 'working', 'issue_id': issue['id'],
                           'base_sha': c1['merge_sha'], 'context_sha256': digest}
    if receipt['issue_id'] != issue['id'] or receipt['context_sha256'] != digest:
        raise ValueError('C2 planning receipt identity drift')
    save_receipt(LEDGER, receipt)
    if issue.get('assignee_id') is None:
        cli('assign', issue['id'], '--to-id', lead)
    task_id, answer = completed_output(issue['id'], lead, timeout=300)
    tracked = subprocess.check_output(['git', '-C', str(selected_project()['checkout']),
                                       'ls-tree', '-r', '--name-only', c1['merge_sha']],
                                      text=True).splitlines()
    old_tests = {name for name in tracked if name.endswith('.py') and
                 name.rsplit('/', 1)[-1].startswith('test_')}
    card = parse(answer, original, old_tests)
    receipt.update(stage='decision_validated', task_id=task_id, card=card,
                   output_sha256=hashlib.sha256(answer.encode()).hexdigest())
    save_receipt(LEDGER, receipt)
    print(json.dumps({'stage': receipt['stage'], 'issue_id': issue['id'],
                      'task_id': task_id, 'files': card['files']}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
