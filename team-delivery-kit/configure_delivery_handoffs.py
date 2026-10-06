"""Register durable handoffs for a pinned portable context; paused by default."""
import argparse
import hashlib
import json
from pathlib import Path

from bootstrap_multica import PRIVATE
from portable_contract import from_environment
from portable_run_spec import load
from prepare_issue_base import broker_post
from release_eval import save_receipt
from start_eval import cli, check_model_budget


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--enable', action='store_true')
    parser.add_argument('--test-first', action='store_true',
                        help='Controller runs Red before any product-code edit')
    args = parser.parse_args()
    contract = from_environment()
    spec = load(contract)
    if not spec:
        raise ValueError('explicit portable run specification required')
    path = PRIVATE / ('portable-context-' + spec['label'] + '.json')
    context = json.loads(path.read_text())
    digest = hashlib.sha256(json.dumps(contract, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    if context['contract_sha256'] != digest or context.get('run_spec_sha256') != spec['sha256']:
        raise ValueError('context contract/specification drift')
    author = json.loads((PRIVATE / spec['implementer_registry']).read_text())['agent_id']
    reviewer = json.loads((PRIVATE / spec['reviewer_registry']).read_text())['agent_id']
    planning = json.loads((PRIVATE / 'planning-agents.json').read_text())['agents']
    route = {'issue_id': context['issue_id'], 'author': author, 'reviewer': reviewer,
             'techlead': planning['techlead'], 'cto': planning['cto'], 'contract_sha256': digest,
             'review_instruction': spec['review_instruction'], 'minimum_calls': 8,
             'enabled': args.enable}
    if args.test_first:
        route.update(test_first=True,
                     test_first_files=sorted(set(contract['test_files']) &
                                             set(contract['editable_files'])))
    active = [w for w in cli('wakeup', 'list', context['issue_id'])
              if w.get('enabled') and w.get('agent_id') in (author, reviewer)
              and not (w.get('instruction') or '').startswith('DELIVERY_HANDOFF ')]
    if active:
        raise ValueError('legacy active wakeups must be paused before migration')
    if args.enable:
        check_model_budget()
        issue = cli('get', context['issue_id'])
        if issue.get('status') in ('done', 'cancelled'):
            raise ValueError('cannot reactivate terminal issue')
        cli('status', context['issue_id'], 'todo', '--no-start')
    broker_post('/v1/delivery-routes', route)
    if not context.get('durable_handoffs'):
        save_receipt(path.with_suffix('.pre-handoffs.json'), context)
        save_receipt(path, {**context, 'durable_handoffs': True})
    print(json.dumps({'issue_id': context['issue_id'], 'enabled': args.enable,
                      'controller': 'broker_durable_handoffs'}))


if __name__ == '__main__':
    main()
