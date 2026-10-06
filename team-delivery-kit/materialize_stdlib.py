"""Expose the CTO-authorized stdlib graph without starting implementation."""
import hashlib
import json

from bootstrap_multica import BACKEND_PORT, PRIVATE
from evalctl import PROJECT
from materialize_plan import ensure_card
from planning_intake import parse_proposal
from release_eval import save_receipt
from start_eval import cli
from stdlib_replan import RUN


def main():
    if PROJECT != 'delivery-kit-port2' or BACKEND_PORT != '19081':
        raise ValueError('stdlib materialization restricted to port2')
    plan = json.loads((PRIVATE / 'replans' / (RUN + '.json')).read_text())
    runtime = json.loads((PRIVATE / 'runtime-alignment' / 'PILOT-FEEDBACK-BOARD.json').read_text())
    if plan.get('stage') != 'plan_ready' or runtime.get('stage') != 'aligned':
        raise ValueError('verified stdlib plan and runtime required')
    proposal = parse_proposal(json.dumps(plan['proposal']), 'techlead')
    plan_sha = hashlib.sha256(json.dumps(proposal, sort_keys=True,
                                         separators=(',', ':')).encode()).hexdigest()
    path = PRIVATE / 'planned-cards' / (RUN + '.json')
    receipt = json.loads(path.read_text()) if path.exists() else {
        'plan_sha256': plan_sha, 'bootstrap_sha': plan['bootstrap_sha'],
        'stage': 'materializing', 'cards': {}}
    if receipt['plan_sha256'] != plan_sha or receipt['bootstrap_sha'] != plan['bootstrap_sha']:
        raise ValueError('stdlib plan identity changed')
    issues = cli('list')['issues']
    for card in proposal['cards']:
        item = ensure_card(card, plan_sha, issues, run_name=RUN,
                           gate_note='Bootstrap is merged; generated delivery contract and independent review are pending.')
        dependencies = [receipt['cards'][key] for key in card['depends_on']]
        metadata = {'planning_run': RUN, 'planning_card': card['id'],
                    'planning_owner': card['owner'], 'planning_sha256': plan_sha,
                    'depends_on_issue_ids': json.dumps(dependencies),
                    'execution_gate': 'awaiting_generated_contract'}
        present = cli('metadata', 'list', item['id'])
        for key, value in metadata.items():
            if key in present and present[key] != value:
                raise ValueError('stdlib card metadata drift')
            if key not in present:
                cli('metadata', 'set', item['id'], '--key', key, '--value', value,
                    '--type', 'string')
        receipt['cards'][card['id']] = item['id']
        save_receipt(path, receipt)
    receipt['stage'] = 'blocked_execution_contract'
    receipt['next_action'] = 'Generate and validate C1 contract from approved agent plan'
    save_receipt(path, receipt)
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
