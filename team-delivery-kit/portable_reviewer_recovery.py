"""At-most-once, reviewer-specific recovery after a failed Multica task."""
import json
import time

from portable_worker_recovery import ACTIVE, RECOVERABLE_REASONS, RecoveryEscalation, latest_run
from release_eval import save_receipt


def reconcile(issue_id, author_id, reviewer_id, runs, issue_status, path, list_wakeups,
              create_wakeup, *, now=None, worker_loss_verified=False):
    if issue_status in ('blocked', 'cancelled', 'done'):
        raise RecoveryEscalation('issue_not_active:' + issue_status)
    if any(run.get('status') in ACTIVE for run in runs):
        return 'worker_active'
    latest = latest_run(runs, reviewer_id)
    if latest is None or latest.get('status') == 'completed':
        return 'awaiting_review'
    if latest.get('status') != 'failed':
        raise RecoveryEscalation('reviewer_not_recoverable:' + str(latest.get('status')))
    if latest.get('issue_id') != issue_id:
        raise RecoveryEscalation('reviewer_issue_identity_mismatch')
    author_runs = [run for run in runs if run.get('agent_id') == author_id
                   and run.get('status') == 'completed']
    if not author_runs:
        raise RecoveryEscalation('reviewer_without_completed_author')
    author = max(author_runs, key=lambda run: (run.get('created_at') or '', run['id']))
    if (author.get('created_at') or '') > (latest.get('created_at') or ''):
        return 'awaiting_review'
    reason = latest.get('failure_reason')
    if reason not in RECOVERABLE_REASONS and not (
            reason == 'agent_error.provider_server_error' and worker_loss_verified):
        raise RecoveryEscalation('nonrecoverable_reviewer_failure:' + str(reason)[:80])
    now = time.time() if now is None else now
    ledger = json.loads(path.read_text()) if path.exists() else None
    newly_persisted = ledger is None
    if ledger:
        if (ledger.get('issue_id') != issue_id or ledger.get('reviewer_id') != reviewer_id
                or ledger.get('source_run_id') != author['id']):
            raise RecoveryEscalation('reviewer_recovery_ledger_identity_mismatch')
        if latest['id'] != ledger.get('failed_run_id'):
            raise RecoveryEscalation('reviewer_recovery_attempt_exhausted')
    else:
        ledger = {'issue_id': issue_id, 'reviewer_id': reviewer_id,
                  'source_run_id': author['id'], 'failed_run_id': latest['id'],
                  'intent_at': now}
        save_receipt(path, ledger)
    marker = 'PORTABLE_REVIEW_RECOVERY ' + latest['id']
    wakeups = list_wakeups(issue_id)
    if not isinstance(wakeups, list):
        raise RecoveryEscalation('reviewer_wakeup_list_invalid')
    matches = [w for w in wakeups if w.get('instruction', '').startswith(marker)]
    if len(matches) > 1:
        raise RecoveryEscalation('duplicate_reviewer_recovery_wakeups')
    if matches:
        wakeup = matches[0]
        if (wakeup.get('agent_id') != reviewer_id or
                wakeup.get('filter_task_id') != latest['id'] or
                wakeup.get('event_types') != ['task.failed'] or
                wakeup.get('kind') != 'event'):
            raise RecoveryEscalation('reviewer_wakeup_identity_mismatch')
        if ledger.get('wakeup_id') and ledger['wakeup_id'] != wakeup.get('id'):
            raise RecoveryEscalation('reviewer_wakeup_id_changed')
        ledger['wakeup_id'] = wakeup['id']
        save_receipt(path, ledger)
        if now - ledger['intent_at'] >= 120:
            raise RecoveryEscalation('reviewer_recovery_not_started')
        return 'recovery_intent_pending'
    if ledger.get('wakeup_id'):
        raise RecoveryEscalation('reviewer_wakeup_disappeared')
    if now - ledger['intent_at'] >= 120:
        raise RecoveryEscalation('reviewer_recovery_dispatch_uncertain')
    # New ledger means this process alone may create it. A restarted process
    # with an intent but no visible wakeup must not race a delayed creation.
    if not newly_persisted:
        return 'recovery_intent_pending'
    created = create_wakeup(issue_id, reviewer_id, latest['id'], marker)
    if (not isinstance(created, dict) or created.get('issue_id') != issue_id or
            created.get('agent_id') != reviewer_id or
            created.get('filter_task_id') != latest['id'] or
            created.get('event_types') != ['task.failed']):
        raise RecoveryEscalation('reviewer_wakeup_creation_identity_mismatch')
    ledger['wakeup_id'] = created['id']
    save_receipt(path, ledger)
    return 'recovery_queued'
