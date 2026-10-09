"""Resume only validation of a completed author after a controller writer fix."""
import hashlib
import json
from pathlib import Path
import time
try:
    from . import handoffs, native, failed_candidate_execution as execution
except ImportError:
    import handoffs, native, failed_candidate_execution as execution

FIXED_SOURCE_SHA='46960e06f74ad0f13dbd6dd2348807f509a9e631db394ff40b8df530dcd44e70'


def prepare(data,task):
    if data.get('sqlite_validation_recovery'):
        if data['sqlite_validation_recovery']['source_task']!=task:raise ValueError('validation recovery identity drift')
        return data
    if (data.get('source_task')!=task or data.get('source_status')!='completed'
            or data.get('error')!='database is locked' or data.get('error_type')!='OperationalError'
            or data.get('dispatch_stage')!='diagnose' or not data.get('bounded_replan_origin')
            or any(data.get(k) for k in ('evidence','review','validation_failure'))
            or type(data.get('attempts')) is not int):
        raise ValueError('legacy controller contention without executed validation evidence required')
    result=json.loads(json.dumps(data))
    result['sqlite_validation_recovery']=dict(operation='completed_author_validation_writer_repair_v1',
        source_task=task,previous_handoff=json.loads(json.dumps(data)),fixed_source_sha256=FIXED_SOURCE_SHA,
        prior_attempts=data['attempts'],author_restarted=False,tests_may_change=False,
        delivery_approval=False,retry_budget_reset=False,attempt_limit=1)
    for field in ('error','error_type','failure_signature','recipient_task','wakeup_id','dispatch_marker',
                  'dispatch_stage','dispatched_at','target','trigger_task','instruction','control_error',
                  'control_error_count','required_action','alerted'):
        result.pop(field,None)
    return result


def tick(b):
    if hashlib.sha256(Path(handoffs.__file__).read_bytes()).hexdigest()!=FIXED_SOURCE_SHA:
        raise ValueError('qualified controller writer source required')
    settings=json.loads((b.STATE/'native.json').read_text())
    with b.db() as con:
        rows=list(con.execute("SELECT source_task,issue_id,stage,data FROM delivery_handoffs WHERE stage IN ('awaiting_acceptance','accepted','technical_decision_required','diagnose_cto')"))
    for row in rows:
        data=json.loads(row['data']);task=row['source_task'];issue=row['issue_id']
        if (data.get('error')!='database is locked' or data.get('error_type')!='OperationalError'
                or data.get('sqlite_validation_recovery') or data.get('sqlite_validation_recovery_incident')):continue
        try:
            with b.db() as con:
                state=execution.load(con,issue)
                route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(issue,)).fetchone()[0])
                if not route.get('enabled'):continue
                latest=con.execute('SELECT source_task FROM delivery_handoffs WHERE issue_id=? ORDER BY updated DESC LIMIT 1',(issue,)).fetchone()[0]
                if (latest!=task or data.get('target')!=route['techlead'] or not state
                        or state.get('status')!='awaiting_delivery_validation'
                        or state.get('terminal',{}).get('task_id')!=task
                        or state.get('terminal',{}).get('status')!='completed'
                        or state['contract_sha256']!=route['contract_sha256']
                        or state['author']!=route['author']):raise ValueError('current completed bounded author required')
                if con.execute('SELECT 1 FROM snapshots WHERE task_id=?',(task,)).fetchone():
                    raise ValueError('snapshot exists; inspect its execution instead of reopening validation')
                leases=con.execute('SELECT l.status FROM leases l JOIN native_bindings n USING(request_id) WHERE n.task_id=?',(task,)).fetchall()
                if len(leases)!=1 or leases[0][0]!='closed':raise ValueError('exact closed completed author lease required')
                if con.execute("SELECT 1 FROM leases l JOIN native_bindings n USING(request_id) WHERE n.issue_id=? AND l.status IN ('creating','starting','running','closing')",(issue,)).fetchone():continue
                repaired=prepare(data,task)
                runs=native.issue_task_runs(settings,issue)
                authors=[r for r in runs if r.get('agent_id')==route['author']]
                record=next((r for r in authors if r['id']==task),{})
                if (not authors or max(authors,key=lambda r:(r.get('created_at') or '',r['id']))['id']!=task
                        or record.get('status')!='completed' or record.get('wakeup_id')!=state.get('wakeup_id')
                        or any(r.get('status') not in ('completed','failed','cancelled','canceled') for r in runs)):
                    raise ValueError('idle native author and diagnosis required')
                current=con.execute('SELECT data FROM delivery_handoffs WHERE source_task=?',(task,)).fetchone()
                if not current or json.loads(current[0])!=data:raise ValueError('validation handoff changed')
                handoffs.save(con,task,issue,'validation_pending',route['reviewer'],repaired,time.time())
        except (ValueError,KeyError,TypeError) as error:
            with b.db() as con:
                current=con.execute('SELECT data FROM delivery_handoffs WHERE source_task=?',(task,)).fetchone()
                if current and json.loads(current[0])==data:
                    data['sqlite_validation_recovery_incident']=dict(category='validation_recovery_precondition_rejected',
                        reason=str(error)[:240],owner='cto',automatic_retry=False,author_restarted=False,delivery_approval=False)
                    handoffs.save(con,task,issue,'technical_decision_required',route['cto'],data,time.time())
