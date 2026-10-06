"""Preserve obsolete planning cards while preventing their dispatch."""
import json

from bootstrap_multica import BACKEND_PORT, PRIVATE
from evalctl import PROJECT
from planning_intake import NAME
from release_eval import save_receipt
from start_eval import cli


def main():
    if PROJECT != 'delivery-kit-port2' or BACKEND_PORT != '19081':
        raise ValueError('supersession restricted to isolated port2')
    spike = json.loads((PRIVATE / 'capability-spikes' / (NAME + '.json')).read_text())
    runtime = json.loads((PRIVATE / 'runtime-alignment' / (NAME + '.json')).read_text())
    if (spike.get('stage') != 'decision_validated'
            or spike['decision']['decision'] != 'stdlib_replan'
            or runtime.get('stage') not in ('blocked_runtime_mismatch',
                                            'blocked_deployment_image_missing')):
        raise ValueError('verified technical supersession required')
    path = PRIVATE / 'planned-cards' / (NAME + '.json')
    receipt = json.loads(path.read_text())
    if receipt['stage'] not in ('blocked_execution_adapter', 'superseded_pending_replan'):
        raise ValueError('unexpected planned-card stage')
    for card_id in receipt['cards'].values():
        card = cli('get', card_id)
        if card['status'] != 'blocked' or card.get('assignee_id'):
            raise ValueError('cannot supersede dispatched work')
        metadata = cli('metadata', 'list', card_id)
        value = spike['issue_id']
        if metadata.get('superseded_by_cto_spike') not in (None, value):
            raise ValueError('supersession metadata drift')
        if 'superseded_by_cto_spike' not in metadata:
            cli('metadata', 'set', card_id, '--key', 'superseded_by_cto_spike',
                '--value', value, '--type', 'string')
    receipt['stage'] = 'superseded_pending_replan'
    receipt['superseded_by_cto_spike'] = spike['issue_id']
    receipt['runtime_gate'] = runtime['stage']
    receipt['next_action'] = 'CTO aligns runtime; Tech Lead replans stdlib implementation'
    save_receipt(path, receipt)
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
