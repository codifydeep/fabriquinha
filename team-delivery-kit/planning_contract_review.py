"""CTO-owned resolution of a plan conflict before execution is authorized."""
import hashlib
import json

from bootstrap_multica import PRIVATE
from materialize_plan import plan_from_ledger
from planning_intake import (intake_configuration, issue_for, completed_output,
                             parse_proposal, validate_execution_plan, tracked_base)
from prepare_issue_base import verified_main
from release_eval import save_receipt
from start_eval import check_model_budget


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def parse_resolution(proposal):
    if proposal.get('role') == 'cto' and 'parameter' in proposal:
        if set(proposal) != {'role', 'parameter', 'absent', 'empty', 'explicit_all', 'unknown', 'reason'}:
            raise ValueError('invalid CTO resolution fields')
        if not isinstance(proposal['reason'], str) or not 1 <= len(proposal['reason']) <= 300:
            raise ValueError('bounded CTO rationale required')
        result = {k: v for k, v in proposal.items() if k not in ('role', 'reason')}
        decisions = None
    else:
        decisions = proposal['technical_decisions']
    if decisions is not None and len(decisions) != 1:
        raise ValueError('one machine-readable CTO contract required')
    if decisions is not None:
        result = json.loads(decisions[0])
    if (not isinstance(result, dict) or set(result) != {'parameter', 'absent', 'empty', 'explicit_all', 'unknown'}
            or result['parameter'] != 'status' or result['absent'] != 'all'
            or result['empty'] not in ('all', '400')
            or result['explicit_all'] not in ('all', '400') or result['unknown'] != '400'):
        raise ValueError('invalid resolved status contract')
    return result


def main():
    selection = intake_configuration()
    if not selection['configuration_sha256'] or selection['name'] != 'FILTER-1':
        raise ValueError('this conflict review is limited to FILTER-1')
    if verified_main() != selection['base_sha']:
        raise ValueError('contract review baseline drift')
    ledger = json.loads((PRIVATE / 'planning-intake' / 'FILTER-1.json').read_text())
    plan = plan_from_ledger(ledger)
    validate_execution_plan(plan, tracked_base(selection))
    identity = {'base_sha': selection['base_sha'], 'plan_sha256': digest(plan),
                'configuration_sha256': selection['configuration_sha256']}
    path = PRIVATE / 'planning-contract-reviews' / 'FILTER-1.json'
    receipt = json.loads(path.read_text()) if path.exists() else {**identity, 'stage': 'intent'}
    if any(receipt.get(k) != v for k, v in identity.items()):
        raise ValueError('contract review identity drift')
    schema_retry = receipt['stage'] == 'blocked' and not receipt.get('schema_retry') and receipt.get('category', '').startswith('JSONDecodeError:')
    if schema_retry:
        receipt.update(schema_retry=1, stage='schema_recovery', rejected_issue_id=receipt['issue_id'])
    if receipt['stage'] in ('decision_validated', 'blocked'):
        print(json.dumps(receipt, sort_keys=True))
        return 0 if receipt['stage'] == 'decision_validated' else 1
    registry = json.loads((PRIVATE / 'planning-agents.json').read_text())
    description = ('DELIVERY_PLANNING_SCHEMA_V1:contract_resolution\n'
        'You are the CTO. Resolve the actual conflict before implementation. '
        'Your prior architecture says empty status means all; the Tech Lead card '
        'says empty status returns 400. Both use parameter status. Decide the '
        'technical API contract yourself; do not ask the CEO. Default absent '
        'status must keep all feedback, unknown must return 400. Also decide '
        'explicit status=all. Return a SINGLE flat JSON object with exactly keys '
        'role, parameter, absent, empty, explicit_all, unknown, reason. role=cto, '
        'parameter=status, absent=all, unknown=400; choose all or 400 '
        'for empty and explicit_all. reason is a concise justification. Never '
        'use placeholders, encoded nested JSON or an architecture proposal. '
        'This is a technical contract, not evidence '
        'of tests or delivery.\nPrior CTO proposal: ' + json.dumps(ledger['outputs']['cto']['proposal']) +
        '\nCurrent Tech Lead plan: ' + json.dumps(plan))
    if len(description) > 8000:
        raise ValueError('contract review context exceeds bound')
    check_model_budget()
    save_receipt(path, receipt)
    issue_id = issue_for('cto', description, registry['agents']['cto'],
                         run_name='FILTER-1-CONTRACT-REVIEW', schema=True)
    receipt.update(stage='working_cto', issue_id=issue_id)
    save_receipt(path, receipt)
    try:
        task, answer = completed_output(issue_id, registry['agents']['cto'])
        proposal = json.loads(answer.strip())
        resolution = parse_resolution(proposal)
    except Exception as error:
        receipt.update(stage='blocked', owner='cto', category=type(error).__name__ + ':' + str(error)[:180])
        save_receipt(path, receipt)
        raise
    receipt.update(stage='decision_validated', task_id=task, resolution=resolution,
                   proposal=proposal, output_sha256=hashlib.sha256(answer.encode()).hexdigest())
    save_receipt(path, receipt)
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
