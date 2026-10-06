"""Persist validated agent-authored cards without dispatching unsupported work."""
import hashlib
import json

from bootstrap_multica import BACKEND_PORT, PRIVATE
from evalctl import PROJECT
from planning_intake import NAME, parse_proposal, intake_configuration, validate_execution_plan, tracked_base
from release_eval import save_receipt
from start_eval import cli


def plan_from_ledger(ledger):
    if ledger.get('stage') != 'plan_ready':
        raise ValueError('planning is not ready')
    outputs = ledger.get('outputs') or {}
    if set(outputs) != {'product', 'cto', 'techlead'}:
        raise ValueError('planning roles incomplete')
    for role, output in outputs.items():
        parse_proposal(json.dumps(output['proposal']), role)
    return outputs['techlead']['proposal']


def card_description(card, plan_sha, gate_note='Controller bootstrap and delivery contracts are pending.'):
    return ('Validated planning proposal; NOT READY FOR EXECUTION. '
            + gate_note + '\n'
            'Plan SHA-256: ' + plan_sha + '\n'
            'Owner: ' + card['owner'] + '\n'
            'Acceptance: ' + json.dumps(card['acceptance'], ensure_ascii=False) + '\n'
            'Proposed files: ' + json.dumps(card['files'], ensure_ascii=False) + '\n'
            'Proposed test command: ' + json.dumps(card['test_command']) + '\n'
            'A Telegram message or this card alone does not authorize a worker.')


def ensure_card(card, plan_sha, existing, run_name=NAME, gate_note=None):
    title = run_name + ' — ' + card['id'] + ' — ' + card['title']
    description = card_description(card, plan_sha, gate_note) if gate_note else card_description(card, plan_sha)
    matches = [item for item in existing if item['title'] == title]
    if len(matches) > 1:
        raise ValueError('duplicate planned card')
    if matches:
        item = matches[0]
        if item['description'] != description or item['status'] != 'blocked' or item.get('assignee_id'):
            raise ValueError('planned card drift or premature dispatch')
        return item
    return cli('create', '--title', title, '--description', description, '--status', 'blocked')


def main():
    if PROJECT != 'delivery-kit-port2' or BACKEND_PORT != '19081':
        raise ValueError('materialization restricted to isolated port2 installation')
    selection = intake_configuration()
    name = selection['name']
    planning_path = PRIVATE / 'planning-intake' / (name + '.json')
    ledger = json.loads(planning_path.read_text())
    if selection['configuration_sha256'] and (
            ledger.get('configuration_sha256') != selection['configuration_sha256']
            or ledger.get('base_sha') != selection['base_sha']
            or ledger.get('brief_sha256') != hashlib.sha256(selection['brief'].read_bytes()).hexdigest()):
        raise ValueError('planning configuration drift before materialization')
    if selection['base_sha']:
        from prepare_issue_base import verified_main
        if verified_main() != selection['base_sha']:
            raise ValueError('planning base changed before materialization')
    proposal = plan_from_ledger(ledger)
    if selection['configuration_sha256']:
        validate_execution_plan(proposal, tracked_base(selection))
    plan_sha = hashlib.sha256(json.dumps(proposal, sort_keys=True,
                                         separators=(',', ':')).encode()).hexdigest()
    receipt_path = PRIVATE / 'planned-cards' / (name + '.json')
    receipt = json.loads(receipt_path.read_text()) if receipt_path.exists() else {
        'plan_sha256': plan_sha, 'stage': 'materializing', 'cards': {}}
    if receipt['plan_sha256'] != plan_sha:
        raise ValueError('planning proposal changed after materialization')
    if receipt.get('stage') == 'superseded_pending_replan':
        print(json.dumps(receipt, sort_keys=True))
        return 0
    existing = cli('list')['issues']
    for card in proposal['cards']:
        item = ensure_card(card, plan_sha, existing, run_name=name)
        dependencies = [receipt['cards'][ident] for ident in card['depends_on']]
        metadata = {'planning_run': name, 'planning_card': card['id'],
                    'planning_owner': card['owner'], 'planning_sha256': plan_sha,
                    'depends_on_issue_ids': json.dumps(dependencies),
                    'execution_gate': 'awaiting_bootstrap_contract'}
        present = cli('metadata', 'list', item['id'])
        for key, value in metadata.items():
            if key in present and present[key] != value:
                raise ValueError('planned card metadata drift')
            if key not in present:
                cli('metadata', 'set', item['id'], '--key', key, '--value', value,
                    '--type', 'string')
        receipt['cards'][card['id']] = item['id']
        save_receipt(receipt_path, receipt)
    receipt['stage'] = 'blocked_execution_adapter'
    receipt['next_action'] = 'Bootstrap baseline tests and build reviewed multi-card execution adapter'
    save_receipt(receipt_path, receipt)
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
