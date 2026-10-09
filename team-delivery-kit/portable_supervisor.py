"""Host-side supervisor for one pinned portable delivery run.

The child controller owns the delivery lock and all side effects. This process
only resumes a paused run when the normal model budget returns and records
unexpected exits; it never changes a card to done or bypasses a QA gate.
"""
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from bootstrap_multica import PRIVATE
from evalctl import verify as verify_instance
from portable_contract import from_environment
from portable_run_spec import load as load_run_spec
from release_eval import save_receipt
from start_eval import check_model_budget
from controller_dispatch_admission import maintenance_active


ROOT = Path(__file__).resolve().parent
COMPLETE = {'deployed_qa_passed', 'qa_recovered_by_child', 'recovered_by_test_revision'}
STOP = {'qa_repair_escalation', 'candidate_replan_required',
        'main_moved_replan_required', 'diagnosis_blocked', 'qa_replan_required',
        'repair_incomplete', 'techlead_diagnosis_timeout',
        'escalation_required', 'cto_escalation_required',
        'cto_diagnosis_failed', 'cto_diagnosis_rejected',
        'cto_diagnosis_blocked', 'cto_diagnosis_timeout',
        'supervisor_escalation', 'test_revision_child_blocked'}
PAUSED = {'budget_paused'}
BUSY = {'repair_controller_busy'}


def read_status(path, label):
    path = Path(path)
    if path.is_symlink():
        raise ValueError('unsafe portable status receipt')
    if not path.exists():
        return None
    if not path.is_file() or path.stat().st_size > 65536:
        raise ValueError('unsafe portable status receipt')
    value = json.loads(path.read_text())
    if not isinstance(value, dict) or value.get('label') != label:
        raise ValueError('portable status label drift')
    return value


def meaningful_change(before, after):
    """A refreshed timestamp alone is not progress and must not reset crashes."""
    if after is None:
        return False
    if before is None:
        return True
    return ({key: value for key, value in before.items() if key != 'updated_at'}
            != {key: value for key, value in after.items() if key != 'updated_at'})


def run_delivery():
    """Fixed child entrypoint; the child's own lock fences orphaned execution."""
    return subprocess.run([sys.executable, str(ROOT / 'portable_delivery.py')],
                          cwd=ROOT, env=os.environ.copy(), check=False).returncode


def stale_size_blocker(status, managed):
    """Reconcile a stale projection only after a durable technical handoff."""
    if (not status or status.get('stage') != 'escalation_required'
            or not status.get('category', '').startswith('test_revision_blocked:')
            or not managed or not managed.get('route', {}).get('enabled')):
        return False
    state = managed.get('state') or {}
    if state.get('stage') not in ('test_review_cto_diagnosis', 'test_revision_required'):
        return False
    details = json.loads(state['data'])
    invalidation = details.get('size_invalidation') or {}
    request = invalidation.get('request') or {}
    diagnosis = details.get('rejection_diagnosis') or {}
    return (request.get('issue_id') == status.get('issue_id')
            and request.get('source_task') == details.get('source_task')
            and request.get('manifest_sha256') == details.get('manifest_sha256')
            and invalidation.get('stage') == 'inadmissible_snapshot_not_review_override'
            and diagnosis.get('status') in ('awaiting_cto', 'revision_required')
            and bool(diagnosis.get('wakeup_id')))


def stale_artifact_diagnosis_blocker(status,managed):
    import hashlib
    if (not status or status.get('stage')!='escalation_required'
            or status.get('category')!='test_first_blocked:test_first_cto_requires_replanning'
            or not managed or not managed.get('route',{}).get('enabled')
            or managed['route'].get('issue_id')!=status.get('issue_id')):return False
    state=managed.get('state') or {}
    if state.get('stage') not in ('technical_decision_required','test_first_cto_diagnosis',
                                  'test_first_cto_correction','test_first_cto_correction_wait'):return False
    data=json.loads(state.get('data','{}'));proof=data.get('artifact_diagnosis_replay') or {}
    diagnostic=data.get('diagnostic') or {}
    return (proof.get('author_retry_authorized') is False and proof.get('delivery_approval') is False
        and diagnostic.get('kind')=='rejected_test_write' and diagnostic.get('issue_id')==status['issue_id']
        and diagnostic.get('task_id')==state.get('source_task')
        and proof.get('diagnostic_sha256')==hashlib.sha256(json.dumps(diagnostic,sort_keys=True).encode()).hexdigest())


def stale_review_transport_blocker(status, managed):
    """A controller-revalidated review handoff may refresh its old UI blocker."""
    if (not status or status.get('stage') != 'escalation_required'
            or status.get('category') != 'technical_decision_required:technical_replanning_required'
            or not managed or not managed.get('route', {}).get('enabled')
            or managed['route'].get('issue_id') != status.get('issue_id')):
        return False
    state = managed.get('state') or {}
    if state.get('stage') not in ('ready_review', 'dispatch_intent', 'awaiting_acceptance', 'accepted', 'approved'):
        return False
    data = json.loads(state.get('data', '{}'))
    receipt = data.get('review_transport_recovery') or {}
    return (receipt.get('error') == 'ValueError:handoff instruction too large'
            and receipt.get('approval') is False and receipt.get('author_restarted') is False
            and receipt.get('manifest_sha256') == data.get('evidence', {}).get('manifest_sha256')
            and bool(receipt.get('manifest_sha256'))
            and data.get('snapshot', {}).get('task_id') == state.get('source_task'))


def stale_restart_blocker(status, managed):
    """Refresh only an old host error after a durable, same-issue diagnosis."""
    if (not status or status.get('stage') != 'escalation_required'
            or not (status.get('category', '').startswith('CalledProcessError:')
                    or status.get('category') in (
                        'technical_decision_required:host_restart_diagnosis_required',
                        'test_first_blocked:test_first_correction_failed_after_cto_diagnosis'))
            or not managed or not managed.get('route', {}).get('enabled')
            or managed['route'].get('issue_id') != status.get('issue_id')):
        return False
    state = managed.get('state') or {}
    if state.get('stage') not in ('technical_decision_required','test_first_cto_diagnosis',
                                  'test_first_cto_correction','test_first_cto_correction_wait'):
        return False
    data = json.loads(state.get('data','{}'))
    receipt = data.get('host_restart_recovery') or {}
    return (receipt.get('request',{}).get('issue_id') == status['issue_id']
            and receipt.get('request',{}).get('source_task') == state.get('source_task')
            and receipt.get('proof',{}).get('baseline_unchanged') is True
            and receipt.get('author_retry_authorized') is False
            and receipt.get('delivery_approval') is False)


def stale_worker_interruption_blocker(status, managed):
    if (not status or status.get('stage') != 'escalation_required'
            or status.get('category') != 'technical_decision_required:author_execution_failed'
            or not managed or not managed.get('route',{}).get('enabled')
            or managed['route'].get('issue_id') != status.get('issue_id')):
        return False
    state=managed.get('state') or {}
    if state.get('stage') not in ('diagnose_cto','dispatch_intent','awaiting_acceptance','accepted','budget_paused','correct_author'):
        return False
    receipt=json.loads(state.get('data','{}')).get('worker_interruption_recovery') or {}
    return (receipt.get('request',{}).get('issue_id') == status['issue_id']
        and receipt.get('request',{}).get('source_task') == state.get('source_task')
        and receipt.get('operation') == 'pre_tool_worker_interruption_recovery_v1'
        and receipt.get('stage') == 'qualified_cto_decision' and receipt.get('probe_status') == 'passed'
        and receipt.get('author_retry_authorized') is False and receipt.get('delivery_approval') is False)


def stale_capsule_review_blocker(status, managed):
    """Refresh an obsolete projection, never approve or dispatch from activity."""
    if (not status or status.get('stage') != 'escalation_required'
            or status.get('category') != 'technical_decision_required:recipient_execution_failed'
            or not managed or managed.get('route', {}).get('enabled') is not True
            or managed['route'].get('issue_id') != status.get('issue_id')):
        return False
    state=managed.get('state') or {}
    if state.get('stage') not in ('awaiting_acceptance','accepted','approved'):
        return False
    capsule=managed['route'].get('execution_context')
    from execution_context import validate
    try: validate(capsule)
    except ValueError: return False
    data=json.loads(state.get('data','{}'));receipt=data.get('review_context_recovery') or {}
    request=receipt.get('request') or {};proof=receipt.get('presentation') or {}
    manifest=data.get('evidence',{}).get('manifest_sha256')
    return (receipt.get('operation')=='native_review_context_recovery_v1'
        and receipt.get('approval') is False and receipt.get('author_restarted') is False
        and request.get('issue_id')==status['issue_id'] and request.get('source_task')==state.get('source_task')
        and proof.get('operation')=='registered_capsule_prompt_probe_v1'
        and proof.get('context_sha256')==capsule['sha256']
        and proof.get('manifest_sha256')==manifest and isinstance(manifest,str) and len(manifest)==64
        and data.get('snapshot',{}).get('task_id')==state.get('source_task'))


def stale_execution_diagnosis_blocker(status, managed):
    """Resume only the newly registered diagnostic, never its terminal verdict."""
    if (not status or status.get('stage') != 'escalation_required'
            or status.get('category') != 'technical_decision_required:recipient_execution_failed'
            or not managed or not managed.get('route', {}).get('enabled')
            or managed['route'].get('issue_id') != status.get('issue_id')):
        return False
    state = managed.get('state') or {}
    if state.get('stage') not in ('diagnose_cto', 'dispatch_intent', 'awaiting_acceptance', 'accepted', 'budget_paused'):
        return False
    data = json.loads(state.get('data', '{}'))
    repair = data.get('execution_diagnosis_contract_repair') or {}
    request = repair.get('request') or {}
    return (request.get('issue_id') == status['issue_id']
        and request.get('source_task') == state.get('source_task')
        and repair.get('repair_kind') == 'preserve_typed_failed_author_scope_v1'
        and repair.get('installed_source_sha') == '3b7e2e6a3391fd58b6913c4b6a81702ed8be1caed0f0de2cdac4edb9df2cbf89'
        and repair.get('author_retry_authorized') is False
        and repair.get('delivery_approval') is False)


def supervise(status_path, ledger_path, label, run, budget_check, pause,
              *, poll_seconds=60, max_unexpected=2):
    """Return an explicit terminal state; a budget pause is never a failure."""
    ledger_path = Path(ledger_path)
    prior = read_status(ledger_path, label) or {}
    unexpected = prior.get('unexpected_exits', 0)
    if type(unexpected) is not int or unexpected < 0:
        raise ValueError('invalid supervisor crash count')
    if prior.get('stage') == 'supervisor_escalation':
        return prior
    initial = read_status(status_path, label)
    if initial and initial.get('stage') in COMPLETE:
        # A receipt from before a host restart is not fresh health evidence.
        exit_code = run()
        refreshed = read_status(status_path, label)
        if exit_code == 0 and refreshed and refreshed.get('stage') in COMPLETE:
            return {'stage': refreshed['stage'], 'result': 'completed'}
        if refreshed and refreshed.get('stage') in STOP:
            return {'stage': refreshed['stage'], 'result': 'visible_blocker'}
        state = {'label': label, 'stage': 'supervisor_escalation',
                 'result': 'visible_blocker', 'unexpected_exits': unexpected + 1,
                 'child_exit_code': exit_code,
                 'last_child_stage': refreshed.get('stage') if refreshed else None,
                 'updated_at': time.time()}
        save_receipt(ledger_path, state)
        return state
    while True:
        before = read_status(status_path, label)
        stage = before.get('stage') if before else None
        if stage in COMPLETE:
            return {'stage': stage, 'result': 'completed'}
        if stage in STOP:
            return {'stage': stage, 'result': 'visible_blocker'}
        if stage in PAUSED:
            try:
                budget_check()
            except (ValueError, OSError, subprocess.CalledProcessError):
                save_receipt(ledger_path, {'label': label, 'stage': 'budget_paused',
                            'unexpected_exits': unexpected, 'updated_at': time.time()})
                pause(poll_seconds)
                continue
        exit_code = run()
        after = read_status(status_path, label)
        new_stage = after.get('stage') if after else None
        if exit_code == 75 or new_stage in BUSY:
            save_receipt(ledger_path, {'label': label, 'stage': 'controller_busy',
                        'unexpected_exits': unexpected, 'updated_at': time.time()})
            pause(30)
            continue
        if new_stage in COMPLETE:
            return {'stage': new_stage, 'result': 'completed'}
        if new_stage in STOP:
            return {'stage': new_stage, 'result': 'visible_blocker'}
        if new_stage == 'waiting_publication_access':
            return {'stage': new_stage, 'result': 'waiting_external_access'}
        if new_stage in PAUSED:
            unexpected = 0
            save_receipt(ledger_path, {'label': label, 'stage': new_stage,
                        'unexpected_exits': unexpected, 'updated_at': time.time()})
            pause(10)
            continue
        changed = meaningful_change(before, after)
        if exit_code != 0 or not changed:
            unexpected += 1
        else:
            unexpected = 0
        if unexpected >= max_unexpected:
            state = {'label': label, 'stage': 'supervisor_escalation',
                     'result': 'visible_blocker', 'unexpected_exits': unexpected,
                     'child_exit_code': exit_code, 'last_child_stage': new_stage,
                     'updated_at': time.time()}
            save_receipt(ledger_path, state)
            return state
        save_receipt(ledger_path, {'label': label, 'stage': new_stage or 'unreported',
                    'unexpected_exits': unexpected, 'child_exit_code': exit_code,
                    'updated_at': time.time()})
        pause(10)


def main():
    # Refuse a supervisor launched with another instance's API ports. A wrong
    # backend can authenticate against the wrong Multica and yield HTTP 401.
    if verify_instance():
        raise ValueError('supervisor instance ports or control plane do not match')
    from evalctl import PROJECT
    if maintenance_active(PROJECT):
        print(json.dumps(dict(stage='maintenance_deferred',owner='devops',product_delivery_changed=False)))
        return 0
    contract = from_environment()
    spec = load_run_spec(contract)
    if not spec:
        raise ValueError('portable supervisor requires a pinned run spec')
    label = spec['label']
    if len(sys.argv) > 1 and sys.argv[1:] != ['--managed-label', label]:
        raise ValueError('supervisor process label differs from pinned run')
    status_path = PRIVATE / 'autonomy-status' / (label + '.json')
    ledger_path = PRIVATE / 'portable-supervisor' / (label + '.json')
    lock_path = PRIVATE / 'portable-supervisor' / (label + '.lock')
    lock_path.parent.mkdir(mode=0o700, exist_ok=True)
    with lock_path.open('a+') as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(json.dumps({'stage':'supervisor_busy','label':label}),flush=True)
            return 75
        def run():
            return run_delivery()
        initial = read_status(status_path, label)
        if initial and initial.get('stage') == 'escalation_required':
            from portable_delivery import read_context, managed_handoff, configure_run
            configure_run(contract)
            context = read_context(contract)
            managed = managed_handoff(context)
            from citation_supervision import eligible as stale_citation_blocker
            from pre_red_supervision import qualified as recovered_pre_red
            from scoped_delivery_supervision import eligible as recovered_scope
            from red_log_supervision import eligible as recovered_red_log
            if (stale_size_blocker(initial, managed) or stale_restart_blocker(initial, managed)
                    or stale_review_transport_blocker(initial, managed)
                    or stale_execution_diagnosis_blocker(initial, managed)
                    or stale_capsule_review_blocker(initial, managed)
                    or stale_citation_blocker(initial, managed)
                    or stale_worker_interruption_blocker(initial, managed)
                    or stale_artifact_diagnosis_blocker(initial, managed)
                    or recovered_pre_red(initial,context)
                    or recovered_scope(initial,context)
                    or recovered_red_log(initial,context)):
                # Read current controller evidence; never rewrite status to success
                # or blindly retry an unchanged terminal blocker.
                run()
        result = supervise(status_path, ledger_path, label, run,
                           check_model_budget, time.sleep)
        if result.get('stage') == 'deployed_qa_passed':
            from portable_test_revision_recovery import reconcile_ancestors
            from start_eval import cli
            result['ancestor_recovery'] = reconcile_ancestors(PRIVATE, label, cli)
    print(json.dumps(result, sort_keys=True), flush=True)
    # A visible technical blocker is a controlled terminal state. A host service
    # should restart on an unhandled crash, not repeatedly respawn this blocker.
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
