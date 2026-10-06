"""Bounded, durable recovery of a failed portable implementation worker.

Only infrastructure/process failures qualify. The intent is written before
calling Multica, so a controller restart can reconcile a possibly accepted
rerun without sending a duplicate request.
"""
import json
from datetime import datetime
from pathlib import Path
import time

from release_eval import save_receipt


RECOVERABLE_REASONS = frozenset({
    'agent_error.process_failure',
    'agent_error.runtime_interrupted',
    'agent_error.worker_lost',
})
ACTIVE = frozenset({'queued', 'running'})
FINAL = frozenset({'completed', 'failed', 'cancelled'})


class RecoveryEscalation(Exception):
    pass


def latest_run(runs, agent_id):
    matching = [run for run in runs if run.get('agent_id') == agent_id]
    if not matching:
        return None
    return max(matching, key=lambda run: (run.get('created_at') or '', run['id']))


def reconcile(issue_id, agent_id, runs, issue_status, path, rerun, *, now=None):
    """Return a stage, dispatching at most one same-issue rerun per failure."""
    if issue_status in ('blocked', 'cancelled', 'done'):
        raise RecoveryEscalation('issue_not_active:' + issue_status)
    if any(run.get('status') in ACTIVE for run in runs):
        return 'worker_active'
    latest = latest_run(runs, agent_id)
    if latest is None or latest.get('status') == 'completed':
        return 'awaiting_review'
    if latest.get('status') not in FINAL:
        return 'worker_settling'
    if latest.get('status') != 'failed':
        raise RecoveryEscalation('worker_cancelled')
    reason = latest.get('failure_reason')
    if reason not in RECOVERABLE_REASONS:
        raise RecoveryEscalation('nonrecoverable_worker_failure:' + str(reason)[:80])
    if latest.get('issue_id') != issue_id:
        raise RecoveryEscalation('worker_issue_identity_mismatch')
    now = time.time() if now is None else now
    ledger = json.loads(path.read_text()) if path.exists() else None
    completed_at = latest.get('completed_at')
    if not ledger and isinstance(completed_at, str):
        try:
            settled_at = datetime.fromisoformat(completed_at.replace('Z', '+00:00')).timestamp()
        except ValueError:
            settled_at = 0
        if now - settled_at < 30:
            return 'worker_settling'
    if ledger:
        if ledger.get('issue_id') != issue_id or ledger.get('agent_id') != agent_id:
            raise RecoveryEscalation('recovery_ledger_identity_mismatch')
        if latest['id'] != ledger.get('source_run_id'):
            raise RecoveryEscalation('recovery_attempt_exhausted')
        if ledger.get('recovery_run_id'):
            # A newer run existed when the controller last reconciled; if it is
            # now absent, stop instead of fabricating another execution.
            if now - ledger['intent_at'] < 120:
                return 'recovery_intent_pending'
            raise RecoveryEscalation('recovery_run_disappeared')
        if now - ledger['intent_at'] >= 120:
            raise RecoveryEscalation('recovery_dispatch_uncertain')
        return 'recovery_intent_pending'
    ledger = {'issue_id': issue_id, 'agent_id': agent_id,
              'source_run_id': latest['id'], 'intent_at': now}
    save_receipt(path, ledger)
    created = rerun(issue_id)
    if (not isinstance(created, dict) or created.get('issue_id') != issue_id
            or created.get('agent_id') != agent_id or created.get('id') == latest['id']):
        raise RecoveryEscalation('recovery_dispatch_identity_mismatch')
    ledger['recovery_run_id'] = created['id']
    save_receipt(path, ledger)
    return 'recovery_queued'
