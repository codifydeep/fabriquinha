"""Ask Tech Lead to replace an obsolete Node graph after CTO/runtime evidence."""
import hashlib
import json

from bootstrap_multica import BACKEND_PORT, PRIVATE
from evalctl import PROJECT
from planning_intake import BRIEF, NAME, brief_body, completed_output, parse_proposal
from release_eval import save_receipt
from start_eval import cli


RUN = NAME + '-STDLIB'


def context(brief, product, decision, main_sha, retry=False):
    text = (
        'YOU ARE THE TECH LEAD. Replace the old Node cards, which are '
        'superseded and must not execute. The CTO chose Python stdlib '
        'http.server + sqlite3 after proving Node dependencies unavailable. '
        'Worker/test/bootstrap-deployment runtimes are pinned and aligned at '
        'Python 3.13.5 / SQLite 3.53.4. The generic health bootstrap is merged '
        'on main at SHA ' + main_sha + '. The existing '
        'Dockerfile.feedback-bootstrap and tests/test_bootstrap_health.py are '
        'protected baseline files; preserve them byte-for-byte. Implement '
        'product features in app/ and add new tests in tests/. The Dockerfile '
        'copies app/ and runs app/server.py. Local Compose may be added, but '
        'do not require cloud or package installs. QA/browser E2E and rollback '
        'remain release gates outside the implementation cards.\n\n'
        + brief + '\n\nVALIDATED PRODUCT STORIES:\n'
        + json.dumps(product, ensure_ascii=False, separators=(',', ':'))
        + '\n\nCTO DECISION:\n'
        + json.dumps(decision, ensure_ascii=False, separators=(',', ':'))
        + '\n\nRETURN EXACTLY ONE JSON OBJECT with role="techlead", '
        'cards (1 to 5) and integration_order. Each card has exactly '
        'id (C1..C5), title, owner, depends_on, acceptance, files, required_files and '
        'test_command. Owners only backend_data, frontend, devops, '
        'quality_security. Dependencies point only to earlier cards. '
        'files is the edit allowlist; required_files is the subset that MUST '
        'exist in the delivered artifact. Do not require speculative module names. '
        'Files are safe relative paths; no protected file may be edited. '
        'Every test_command is exactly '
        '["python3","-m","unittest","discover","-s",".","-q"]. '
        'Every card acceptance includes TDD/Red-Green/full-suite and preservation '
        'of old tests when it changes code. Do not claim execution or ask the CEO '
        'to decide architecture. No Markdown.')
    if retry:
        text = ('FORMAT CORRECTION: Reply only with one valid compact JSON object '
                'under 7000 characters. Use at most 5 cards, short strings, '
                'and exactly the field names specified below.\n\n' + text)
    if len(text) > 8000:
        raise ValueError('stdlib replan context too large')
    return text


def main():
    if PROJECT != 'delivery-kit-port2' or BACKEND_PORT != '19081':
        raise ValueError('stdlib replan restricted to isolated port2')
    prior = json.loads((PRIVATE / 'planning-intake' / (NAME + '.json')).read_text())
    old = json.loads((PRIVATE / 'planned-cards' / (NAME + '.json')).read_text())
    spike = json.loads((PRIVATE / 'capability-spikes' / (NAME + '.json')).read_text())
    runtime = json.loads((PRIVATE / 'runtime-alignment' / (NAME + '.json')).read_text())
    if (prior.get('stage') != 'plan_ready' or old.get('stage') != 'superseded_pending_replan'
            or spike.get('stage') != 'decision_validated'
            or spike['decision']['decision'] != 'stdlib_replan'
            or runtime.get('stage') != 'aligned'):
        raise ValueError('CTO decision, supersession and runtime alignment required')
    from bootstrap_review import command, REPO
    main_sha = command('gh', 'api', 'repos/' + REPO + '/git/ref/heads/main', '--jq', '.object.sha')
    bootstrap = command('gh', 'pr', 'view', '16', '-R', REPO,
                        '--json', 'state,mergeCommit')
    merged = json.loads(bootstrap)
    if merged['state'] != 'MERGED' or merged['mergeCommit']['oid'] != main_sha:
        raise ValueError('bootstrap main identity changed')
    base = brief_body(BRIEF.read_text())
    product = prior['outputs']['product']['proposal']
    decision = spike['decision']
    path = PRIVATE / 'replans' / (RUN + '.json')
    existing = json.loads(path.read_text()) if path.exists() else None
    if (existing and existing.get('stage') == 'blocked'
            and existing.get('category') == 'ValueError:invalid proposed file'
            and not existing.get('dotfile_policy_revalidated')):
        existing['stage'] = 'revalidating_completed_output'
        existing['dotfile_policy_revalidated'] = 1
        save_receipt(path, existing)
    if existing and existing.get('stage') in ('plan_ready', 'blocked'):
        if existing['stage'] == 'plan_ready':
            existing.pop('category', None)
            existing.pop('owner', None)
            save_receipt(path, existing)
        print(json.dumps(existing, sort_keys=True))
        return 0 if existing['stage'] == 'plan_ready' else 1
    retry = bool(existing and existing.get('retry_format'))
    description = context(base, product, decision, main_sha, retry)
    digest = hashlib.sha256(description.encode()).hexdigest()
    receipt = existing or {'run': RUN, 'stage': 'planned', 'attempts': []}
    title = RUN + ' — techlead' + ('-format-retry1' if retry else '')
    matches = [issue for issue in cli('list')['issues'] if issue['title'] == title]
    if len(matches) > 1:
        raise ValueError('duplicate replan issue')
    issue = matches[0] if matches else cli('create', '--title', title,
                                           '--description', description, '--status', 'todo')
    if issue['description'] != description:
        raise ValueError('replan description drift')
    agent = json.loads((PRIVATE / 'planning-agents.json').read_text())['agents']['techlead']
    if issue.get('assignee_id') not in (None, agent):
        raise ValueError('replan agent drift')
    receipt.update(stage='working', active_issue_id=issue['id'],
                   context_sha256=digest, bootstrap_sha=main_sha)
    save_receipt(path, receipt)
    if issue.get('assignee_id') is None:
        cli('assign', issue['id'], '--to-id', agent)
    try:
        task_id, answer = completed_output(issue['id'], agent)
        proposal = parse_proposal(answer, 'techlead')
        if any(card['test_command'] != ['python3', '-m', 'unittest', 'discover', '-s', '.', '-q']
               for card in proposal['cards']):
            raise ValueError('non-Python card in stdlib replan')
        protected = {'Dockerfile.feedback-bootstrap', 'tests/test_bootstrap_health.py',
                     'tests/__init__.py'}
        if any(protected.intersection(card['files']) for card in proposal['cards']):
            raise ValueError('replan edits protected bootstrap files')
        receipt.update(stage='plan_ready', proposal=proposal, task_id=task_id,
                       output_sha256=hashlib.sha256(answer.encode()).hexdigest())
    except Exception as error:
        category = (type(error).__name__ + ':' + str(error))[:160]
        receipt['attempts'].append({'issue_id': issue['id'], 'category': category})
        if not retry and isinstance(error, (ValueError, json.JSONDecodeError)):
            receipt.update(stage='retry_format', retry_format=1)
            save_receipt(path, receipt)
            return main()
        receipt.update(stage='blocked', owner='techlead', category=category)
    save_receipt(path, receipt)
    print(json.dumps(receipt, sort_keys=True))
    return 0 if receipt['stage'] == 'plan_ready' else 1


if __name__ == '__main__':
    raise SystemExit(main())
