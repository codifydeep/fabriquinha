"""Route a verified execution-capability mismatch to the CTO, once."""
import hashlib
import json

from bootstrap_multica import BACKEND_PORT, PRIVATE
from evalctl import PROJECT
from planning_intake import NAME, completed_output
from release_eval import save_receipt
from start_eval import cli


TITLE = NAME + ' — CTO-SPIKE dependency availability'
DESCRIPTION = (
    'YOU ARE THE CTO. Verified infrastructure evidence: the pinned offline Node '
    'test image contains neither express nor better-sqlite3 (both require.resolve '
    'checks returned missing). The implementation worker has no package-registry '
    'access, and test containers run without network. Your prior feedback-board '
    'architecture selected Node + Express + better-sqlite3. Choose exactly one '
    'technical resolution: (A) controller-provisioned, pinned and reviewed '
    'dependency bundle made available identically to worker, test and deployment; '
    'or (B) replan with the available Python standard library http.server + sqlite3 '
    'while preserving the CEO brief. No CEO decision is needed. '
    'Return ONLY JSON: {"role":"cto","decision":"dependency_bundle" or '
    '"stdlib_replan","rationale":"one concise reason",'
    '"downstream_actions":["concrete next action"]}. '
    'Do not claim to have installed packages, edited code or changed cards.'
)


def parse_decision(text):
    if not isinstance(text, str) or not 0 < len(text) <= 1600:
        raise ValueError('invalid CTO spike output size')
    value = json.loads(text.strip())
    if not isinstance(value, dict) or set(value) != {
            'role', 'decision', 'rationale', 'downstream_actions'}:
        raise ValueError('invalid CTO spike schema')
    if value['role'] != 'cto' or value['decision'] not in ('dependency_bundle', 'stdlib_replan'):
        raise ValueError('invalid CTO authority or option')
    if not isinstance(value['rationale'], str) or not 10 <= len(value['rationale']) <= 600:
        raise ValueError('invalid CTO rationale')
    actions = value['downstream_actions']
    if not isinstance(actions, list) or not 1 <= len(actions) <= 5 or any(
            not isinstance(item, str) or not 5 <= len(item) <= 400 for item in actions):
        raise ValueError('invalid downstream actions')
    return value


def main():
    if PROJECT != 'delivery-kit-port2' or BACKEND_PORT != '19081':
        raise ValueError('CTO spike restricted to isolated port2')
    plan = json.loads((PRIVATE / 'planning-intake' / (NAME + '.json')).read_text())
    cards = json.loads((PRIVATE / 'planned-cards' / (NAME + '.json')).read_text())
    if plan.get('stage') != 'plan_ready' or cards.get('stage') != 'blocked_execution_adapter':
        raise ValueError('planning and blocked cards required')
    if 'Express' not in plan['outputs']['cto']['proposal']['stack'] or 'better-sqlite3' not in plan['outputs']['cto']['proposal']['stack']:
        raise ValueError('verified mismatch no longer matches CTO plan')
    agent = json.loads((PRIVATE / 'planning-agents.json').read_text())['agents']['cto']
    path = PRIVATE / 'capability-spikes' / (NAME + '.json')
    receipt = json.loads(path.read_text()) if path.exists() else {
        'evidence_sha256': hashlib.sha256(DESCRIPTION.encode()).hexdigest(),
        'stage': 'planned'}
    if receipt['evidence_sha256'] != hashlib.sha256(DESCRIPTION.encode()).hexdigest():
        raise ValueError('spike evidence changed')
    if receipt['stage'] == 'decision_validated':
        for stale in ('category', 'owner', 'next_action'):
            receipt.pop(stale, None)
        save_receipt(path, receipt)
        print(json.dumps(receipt, sort_keys=True))
        return 0
    if (receipt['stage'] == 'blocked'
            and receipt.get('category') == 'ValueError:invalid CTO rationale'
            and not receipt.get('rationale_policy_revalidated')):
        receipt['stage'] = 'revalidating_completed_output'
        receipt['rationale_policy_revalidated'] = 1
        save_receipt(path, receipt)
    if (receipt['stage'] == 'blocked'
            and receipt.get('category') == 'ValueError:invalid downstream actions'
            and not receipt.get('actions_policy_revalidated')):
        receipt['stage'] = 'revalidating_completed_output'
        receipt['actions_policy_revalidated'] = 1
        save_receipt(path, receipt)
    if receipt['stage'] in ('decision_validated', 'blocked'):
        print(json.dumps(receipt, sort_keys=True))
        return 0 if receipt['stage'] == 'decision_validated' else 1
    matches = [item for item in cli('list')['issues'] if item['title'] == TITLE]
    if len(matches) > 1:
        raise ValueError('duplicate CTO spike')
    issue = matches[0] if matches else cli('create', '--title', TITLE,
                                           '--description', DESCRIPTION, '--status', 'todo')
    if issue['description'] != DESCRIPTION or issue.get('assignee_id') not in (None, agent):
        raise ValueError('CTO spike issue drift')
    receipt.update(stage='working', issue_id=issue['id'])
    save_receipt(path, receipt)
    if issue.get('assignee_id') is None:
        cli('assign', issue['id'], '--to-id', agent)
    try:
        task_id, answer = completed_output(issue['id'], agent)
        decision = parse_decision(answer)
        receipt.update(stage='decision_validated', task_id=task_id,
                       decision=decision, output_sha256=hashlib.sha256(answer.encode()).hexdigest())
    except Exception as error:
        receipt.update(stage='blocked', category=(type(error).__name__ + ':' + str(error))[:160],
                       owner='cto', next_action='Diagnose SPIKE output; do not repeat identical prompt')
    save_receipt(path, receipt)
    print(json.dumps(receipt, sort_keys=True))
    return 0 if receipt['stage'] == 'decision_validated' else 1


if __name__ == '__main__':
    raise SystemExit(main())
