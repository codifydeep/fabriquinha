"""Automatic qualification of the existing recorded pre-tool SIGKILL recovery.

Not a generic process-failure retry: a controller-owned fault receipt, historical
Red and completed independent CTO diagnosis are mandatory. The broker checks
the native identities, idle leases, offline probe and frozen-file preservation.
"""
import json
from pathlib import Path
import re
import subprocess
import uuid
from automatic_restart_diagnosis import invoke
from release_eval import save_receipt

CATEGORY='technical_decision_required:author_execution_failed'
PRECHECK='''import json,sys,broker as b
issue,source=sys.argv[1:]
p=b.STATE/'fault-injection'/(source+'.json')
result=False
if p.exists() and not p.is_symlink() and p.stat().st_size<=4096:
 d=json.loads(p.read_text())
 result=(d.get('issue_id')==issue and d.get('task_id')==source and d.get('signal')=='SIGKILL'
  and d.get('accepted_tools_before')==0 and d.get('ownership_revalidated') is True)
print(json.dumps(result))
'''
REGISTER='''import json,sys,broker as b,worker_interruption_recovery as r
issue,source,decision=sys.argv[1:]
print(json.dumps(r.register(b,dict(issue_id=issue,source_task=source,decision_task=decision))))
'''
LOOKUP='''import json,sys,broker as b
with b.db() as c:
 exists=c.execute("SELECT 1 FROM sqlite_master WHERE name='worker_interruption_recoveries'").fetchone()
 row=c.execute("SELECT receipt FROM worker_interruption_recoveries WHERE issue_id=?",(sys.argv[1],)).fetchone() if exists else None
 print(row[0] if row else 'null')
'''
ADVANCE='''import json,sys,broker as b,worker_interruption_recovery as r
with b.db() as c:
 row=c.execute("SELECT receipt FROM worker_interruption_recoveries WHERE issue_id=?",(sys.argv[1],)).fetchone()
if not row:raise ValueError('existing probe intent required')
receipt=json.loads(row[0])
if receipt['request']!=dict(issue_id=sys.argv[1],source_task=sys.argv[2],decision_task=sys.argv[3]):
 raise ValueError('probe identity drift')
print(json.dumps(r.register(b,receipt['request'])))
'''


def eligible(status,managed):
    if (not status or status.get('stage')!='escalation_required' or status.get('category')!=CATEGORY
            or not managed or not managed.get('route',{}).get('enabled')):return False
    route,state=managed['route'],managed.get('state') or {}
    data=json.loads(state.get('data','{}'));phase=data.get('phase_evidence') or {}
    return (route.get('issue_id')==status.get('issue_id') and state.get('stage')=='technical_decision_required'
        and state.get('owner')==route.get('cto') and route.get('author')!=route.get('cto')
        and data.get('target')==route.get('cto') and data.get('source_status')=='failed'
        and data.get('source_failure_reason')=='agent_error.process_failure'
        and data.get('error')=='author_execution_failed' and data.get('decision',{}).get('action')=='escalate_cto'
        and data.get('decision',{}).get('optional_files')==[] and bool(data.get('recipient_task'))
        and phase.get('phase')=='implementation' and phase.get('red_exit_code')==1
        and phase.get('independent_test_review')=='approved' and bool(phase.get('frozen_test_hashes'))
        and not data.get('validation_failure') and not data.get('execution_repair')
        and not data.get('worker_interruption_recovery_used'))


def valid(receipt,identity):
    if not isinstance(receipt,dict):return False
    proof=receipt.get('proof') or {}
    if not isinstance(proof,dict):return False
    return (isinstance(receipt,dict) and receipt.get('request')==identity
        and receipt.get('stage')=='qualified_cto_decision' and receipt.get('probe_status')=='passed'
        and receipt.get('operation')=='pre_tool_worker_interruption_recovery_v1'
        and receipt.get('author_retry_authorized') is False and receipt.get('delivery_approval') is False
        and proof.get('baseline_unchanged') is True and proof.get('frozen_tests_unchanged') is True
        and proof.get('diagnostic_only') is True and proof.get('red_verified') is False
        and proof.get('delivery_approval') is False)


def reconcile(private,instance,status,managed,operation=invoke):
    if not eligible(status,managed):return False
    state=managed['state'];data=json.loads(state['data'])
    identity=dict(issue_id=status['issue_id'],source_task=state['source_task'],decision_task=data['recipient_task'])
    if not re.fullmatch(r'[A-Z][A-Z0-9]{1,31}-[1-9][0-9]{0,5}',status['label']):
        raise ValueError('worker recovery label invalid')
    for value in identity.values():
        if str(uuid.UUID(value))!=value:raise ValueError('canonical recovery identity required')
    path=Path(private)/'host-service'/(status['label']+'.worker-interruption.json')
    if path.is_symlink() or path.parent.is_symlink():raise ValueError('unsafe recovery receipt')
    prior=json.loads(path.read_text()) if path.exists() else None
    if prior:
        if prior.get('identity')!=identity:return False
        if prior.get('stage')=='registered':return valid(prior.get('receipt'),identity)
        if prior.get('stage') not in ('intent','probe_pending'):return False
        if prior.get('stage')=='probe_pending' and prior.get('polls',0)>=2:
            save_receipt(path,dict(identity=identity,stage='diagnosis_blocked',reason='probe_reconciliation_exhausted',
                author_retry_authorized=False,next_action='cto_inspect_existing_probe_without_redispatch'))
            return False
        script,args=(LOOKUP,(identity['issue_id'],)) if prior['stage']=='intent' else (ADVANCE,tuple(identity.values()))
    else:
        try:has_fault=operation(instance,PRECHECK,identity['issue_id'],identity['source_task'])
        except (ValueError,OSError,subprocess.TimeoutExpired):return False
        if has_fault is not True:return False
        prior=dict(identity=identity,stage='intent',polls=0,
                   next_action='lookup_durable_registration_without_redispatch')
        save_receipt(path,prior)  # before first mutation
        script,args=REGISTER,tuple(identity.values())
    try:receipt=operation(instance,script,*args)
    except (ValueError,OSError,subprocess.TimeoutExpired):
        polls=prior.get('polls',0)+1
        if polls>=2:
            save_receipt(path,dict(identity=identity,stage='diagnosis_blocked',reason='registration_observation_unresolved',
                author_retry_authorized=False,next_action='cto_inspect_existing_intent_without_redispatch'))
            return False
        save_receipt(path,dict(identity=identity,stage='intent',polls=polls,
            next_action='lookup_existing_broker_receipt_then_cto_diagnosis'))
        return False
    if valid(receipt,identity):
        save_receipt(path,dict(identity=identity,stage='registered',receipt=receipt));return True
    if isinstance(receipt,dict) and receipt.get('request')==identity and receipt.get('stage')=='probe_pending':
        polls=prior.get('polls',0)+(1 if script==ADVANCE else 0)
        save_receipt(path,dict(identity=identity,stage='probe_pending',polls=polls,
            author_retry_authorized=False,next_action='advance_existing_probe_without_resubmission'))
        return False
    save_receipt(path,dict(identity=identity,stage='diagnosis_blocked',reason='no_qualified_registration',
        author_retry_authorized=False,next_action='cto_inspect_preserved_failure_without_author_retry'))
    return False
