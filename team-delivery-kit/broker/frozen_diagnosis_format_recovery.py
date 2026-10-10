"""Once-only CTO format recovery over a completed, immutable failed delivery.

Only a durable dispatch intent is produced. Ordinary handoff reconciliation owns
wakeup observation, grants and decision validation. No author or test permissions.
"""
import copy
import hashlib
import json
from pathlib import Path
import re
import time
import uuid

OPERATION='frozen_suite_cto_optional_files_recovery_v1'
LIVE=('creating','starting','running','active','closing')


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()


def prepare(e):
    row,route,source,failed,q=(e[k] for k in ('row','route','source','failed','qualification'))
    data=json.loads(row['data']);failure=data.get('validation_failure',{})
    rejection=e['rejection'];diagnostic=rejection.get('constraint_diagnostic',{})
    result=e['job'].get('result',{});binding=e['binding']
    for value in (row['source_task'],row['issue_id'],source['id'],failed['id'],binding['request_id']):
        if str(uuid.UUID(value))!=value:raise ValueError('canonical recovery identities required')
    paths=failure.get('diagnostic_read_files',[])
    if not paths or any(not re.fullmatch(r'[A-Za-z0-9_./-]+',p) or '..' in p.split('/') or p.startswith('/') for p in paths):
        raise ValueError('bounded immutable diagnostic files required')
    previous=sorted(p for p in paths if p.startswith('tests/') and p.endswith('.py'))
    expected={ '/evidence/candidate/'+p for p in paths }
    reads=e['reads']
    if (not previous or len(paths)>16 or len(previous)>8
            or any(type(reads.get(p,{}).get('lines')) is not int or reads[p]['lines']<=0
                   or reads[p]['lines']!=reads[p].get('total_lines') for p in expected)):
        raise ValueError('actual complete candidate inspection required')
    if (row['stage']!='technical_decision_required' or row['owner']!=route['cto']
            or row['issue_id']!=route['issue_id'] or row['source_task']!=source['id']
            or route.get('enabled') is not True or route.get('test_first')
            or route['author']==route['cto'] or source.get('agent_id')!=route['author']
            or source.get('status')!='completed' or e['latest_author']!=source['id']
            or failed.get('agent_id')!=route['cto'] or failed.get('status')!='failed'
            or failed.get('failure_reason')!='agent_error.provider_server_error'
            or failed.get('wakeup_id')!=data.get('wakeup_id') or failed['id']!=data.get('recipient_task')
            or data.get('target')!=route['cto'] or data.get('failed_dispatch_stage')!='diagnose_cto'
            or data.get('error')!='recipient_execution_failed' or data.get('artifact_diagnosis') is not True
            or data.get('frozen_diagnosis_format_recovery') or e['consumed'] or e['active'] or e['pending']
            or binding.get('agent_id')!=route['cto'] or binding.get('issue_id')!=row['issue_id']
            or binding.get('status')!='closed' or binding.get('scope','').split(':')[-2:]!=['planning',failed['id']]
            or e['snapshot'].get('status')!='complete' or e['snapshot'].get('task_id')!=source['id']
            or e['snapshot'].get('volume')!=failure.get('volume')
            or failure.get('source_task')!=source['id'] or failure.get('phase')!='frozen_green'
            or failure.get('category')!='executed_test_failure' or failure.get('exit_code')!=1
            or type(failure.get('tests_executed')) is not int or failure['tests_executed']<=0
            or e['job'].get('stage')!='complete' or result.get('exit_code')!=1
            or e['job_task']!=source['id'] or e['job_kind']!='suite'
            or result.get('output_sha256')!=failure.get('output_sha256')
            or result.get('approval') is not False or e['job'].get('approval') is not False
            or q.get('operation')!='provider_optional_files_transport_qualification_v1'
            or q.get('actual_artifact_read') is not False or q.get('delivery_approval') is not False
            or q.get('author_retry_authorized') is not False or q.get('test_change_authorized') is not False
            or q.get('optional_feedback_enabled') is not True or q.get('proxy_image')!=e['proxy_image']
            or rejection.get('operation')!='rejected_typed_decision_adapter_v1'
            or rejection.get('category')!='typed_schema_maxItems'
            or rejection.get('delivery_approval') is not False or rejection.get('worker_tool_executed') is not False
            or diagnostic.get('constraints')!=['maxItems'] or diagnostic.get('root_constraints')!=['maxItems']
            or diagnostic.get('locations')!=['optional_file_count']
            or diagnostic.get('schema_sha256')!=q.get('adapter_receipt',{}).get('schema_sha256')
            or not re.fullmatch(r'[a-f0-9]{64}',rejection.get('upstream_sha256',''))
            or e['remaining']<route['minimum_calls']):
        raise ValueError('idle immutable source-bound CTO format incident required')
    try:import provider_diagnosis_recovery as registration
    except ImportError:from broker import provider_diagnosis_recovery as registration
    registration.validate_canary(q['event'],q['adapter_receipt'],q['execution_id'],
                                 q['response_sha256'],diagnostic['schema_sha256'])
    registration.validate_optional_canary(q['event'],q['adapter_receipt'],
        dict(optional_feedback_enabled=q['optional_feedback_enabled'],optional_sources=q['optional_sources'],
             routing_sha256=q['routing_sha256']),e['expected_sources'])
    instruction=data.get('instruction','')
    if ('DELIVERY_STRUCTURED_DECISION_V1:technical' not in instruction
            or 'DELIVERY_TYPED_DECISION_V1' not in instruction
            or any('DELIVERY_REVIEW_READ_PATH:'+p+'\n' not in instruction for p in expected)):
        raise ValueError('original source-bound typed inspection instruction required')
    proof=dict(operation=OPERATION,qualification=q,rejection=rejection,
        failed_task=failed['id'],failed_execution=binding['request_id'],previous_handoff=copy.deepcopy(row),
        author_retry_authorized=False,test_change_authorized=False,delivery_approval=False,
        attempts_preserved=True)
    instruction+=('\nONE CONTROLLER-QUALIFIED FORMAT RECOVERY. The previous local validator rejected '
        'optional_files cardinality; no technical verdict was accepted. Diagnose the SAME frozen '
        'failure. Do not infer that a test is defective. Read the previous frozen tests below '
        'as well as ALL candidate paths before deciding. optional_files MUST be []. '
        'Any proxy format resubmission must preserve its action and reason exactly. '
        'No author restart, test edit, fresh Red, merge or release approval is granted.\n')
    instruction+=''.join('DELIVERY_REVIEW_READ_PATH:/evidence/previous/'+p+'\n' for p in previous)
    updated=copy.deepcopy(data)
    updated.update(frozen_diagnosis_format_recovery=proof,
        diagnostic_revision=data['diagnostic_revision']+':'+OPERATION,trigger_task=failed['id'])
    marker=digest(dict(source=source['id'],failed=failed['id'],operation=OPERATION,proof=digest(proof)))
    for field in ('recipient_task','wakeup_id','dispatched_at','alerted','decision','control_error','control_error_count'):
        updated.pop(field,None)
    updated.update(dispatch_marker=marker,dispatch_stage='diagnose_cto',target=route['cto'],instruction=instruction)
    return updated,proof


def apply_transition(c,row,route,updated,proof,now):
    try:import handoffs
    except ImportError:from broker import handoffs
    if not c.in_transaction:c.execute('BEGIN IMMEDIATE')
    c.execute('CREATE TABLE IF NOT EXISTS frozen_diagnosis_format_recoveries(source_task TEXT PRIMARY KEY,proof TEXT)')
    if c.execute('SELECT 1 FROM frozen_diagnosis_format_recoveries WHERE source_task=?',(row['source_task'],)).fetchone():return False
    if handoffs.load(c,row['source_task'])!=row:raise ValueError('handoff changed before format recovery')
    if c.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','active','closing')").fetchone():
        raise ValueError('execution began before format recovery')
    c.execute('INSERT INTO frozen_diagnosis_format_recoveries VALUES(?,?)',(row['source_task'],json.dumps(proof,sort_keys=True)))
    handoffs.save(c,row['source_task'],row['issue_id'],'dispatch_intent',route['cto'],updated,now,commit=False)
    return True


def reconcile(b,source_id,*,preview=False):
    try:import handoffs,native,handoff_runtime,controller_maintenance,provider_diagnosis_recovery as registration,execution_diagnosis_recovery
    except ImportError:
        from broker import handoffs,native,handoff_runtime,controller_maintenance,provider_diagnosis_recovery as registration,execution_diagnosis_recovery
    with b.LOCK:
        with b.db() as c:
            if controller_maintenance.current(c) and not preview:return False
            if not c.execute("SELECT 1 FROM sqlite_master WHERE name='provider_optional_files_qualifications'").fetchone():return False
            exists=c.execute("SELECT 1 FROM sqlite_master WHERE name='frozen_diagnosis_format_recoveries'").fetchone()
            if exists and c.execute('SELECT 1 FROM frozen_diagnosis_format_recoveries WHERE source_task=?',(source_id,)).fetchone():return False
            row=handoffs.load(c,source_id)
            if not row or row['stage']!='technical_decision_required':return False
            data=json.loads(row['data'])
            if data.get('error')!='recipient_execution_failed' or data.get('failed_dispatch_stage')!='diagnose_cto' or not data.get('artifact_diagnosis'):return False
            route=json.loads(c.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(row['issue_id'],)).fetchone()[0])
            latest=c.execute('SELECT source_task FROM delivery_handoffs WHERE issue_id=? ORDER BY updated DESC LIMIT 1',(row['issue_id'],)).fetchone()
            if latest[0]!=source_id:return False
            qrow=c.execute('SELECT proof FROM provider_optional_files_qualifications ORDER BY at DESC LIMIT 1').fetchone()
            if not qrow:return False
            q=json.loads(qrow[0]);proxy=registration.proxy_info(b)
            if (proxy['Image']!=q['proxy_image'] or proxy.get('HostConfig',{}).get('ReadonlyRootfs') is not True
                    or 'MODEL_PROXY_OPTIONAL_FILES_FEEDBACK=1' not in proxy['Config'].get('Env',[])):return False
            bindings=c.execute('SELECT n.*,l.status FROM native_bindings n JOIN leases l USING(request_id) WHERE n.task_id=?',(data.get('recipient_task'),)).fetchall()
            snaps=c.execute('SELECT * FROM snapshots WHERE task_id=?',(source_id,)).fetchall()
            if len(bindings)!=1 or len(snaps)!=1:return False
            binding=dict(bindings[0]);snapshot=dict(snaps[0])
            jobs=[]
            for job in c.execute('SELECT identity,state FROM validation_jobs'):
                identity=json.loads(job[0]);state=json.loads(job[1])
                if identity.get('task')==source_id and identity.get('kind')=='suite':jobs.append((identity,state))
            if len(jobs)!=1:return False
            active=bool(c.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','active','closing')").fetchone())
        settings=json.loads((b.STATE/'native.json').read_text());runs=native.issue_task_runs(settings,row['issue_id'])
        authors=[r for r in runs if r.get('agent_id')==route['author']]
        source=next((r for r in runs if r['id']==source_id),None)
        failed=next((r for r in runs if r['id']==data.get('recipient_task')),None)
        if not source or not failed or not authors:return False
        if (source.get('status')!='completed' or failed.get('status')!='failed'
                or failed.get('failure_reason')!='agent_error.provider_server_error'
                or failed.get('agent_id')!=route['cto'] or active
                or any(r.get('status') in ('queued','dispatched','running') for r in runs)):return False
        import importlib.util
        sources={name:hashlib.sha256(Path(importlib.util.find_spec(name).origin).read_bytes()).hexdigest()
                 for name in registration.OPTIONAL_SOURCE_NAMES}
        try:
            rejection=execution_diagnosis_recovery.format_rejection(b,binding['request_id'],expected_image=q['proxy_image'])
        except ValueError:return False  # Other provider incidents cannot starve unrelated handoffs.
        effects=handoff_runtime.Effects(b,settings)
        try:
            updated,proof=prepare(dict(row=row,route=route,source=source,failed=failed,qualification=q,
                rejection=rejection,binding=binding,snapshot=snapshot,job=jobs[0][1],job_task=jobs[0][0]['task'],job_kind=jobs[0][0]['kind'],
                reads=effects.read_evidence(failed),expected_sources=sources,proxy_image=proxy['Image'],consumed=False,active=active,
                latest_author=max(authors,key=lambda r:(r.get('created_at') or '',r['id']))['id'],
                pending=any(r.get('status') in ('queued','dispatched','running') for r in runs),remaining=effects.remaining_calls()))
        except ValueError:return False
        if registration.proxy_info(b)['Id']!=proxy['Id']:raise ValueError('proxy changed before recovery')
        if preview:return dict(operation=OPERATION,eligible=True,source_task=source_id,failed_task=failed['id'],
            proof_sha256=digest(proof),failure_sha256=digest(data['validation_failure']),
            instruction_chars=len(updated['instruction']),dispatch_created=False,
            author_retry_authorized=False,test_change_authorized=False,delivery_approval=False)
        with b.db() as c:
            if controller_maintenance.current(c):return False
            return apply_transition(c,row,route,updated,proof,time.time())


def tick(b):
    with b.db() as c:
        rows=c.execute("SELECT source_task FROM delivery_handoffs WHERE stage='technical_decision_required'").fetchall()
    for row in rows:reconcile(b,row[0])
