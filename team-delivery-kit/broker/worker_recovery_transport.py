"""One evidence-bound replay after a truncated plain-JSON runtime request.

No worker endpoint, no author restart and no invented technical decision.
"""
import hashlib
import json
from pathlib import Path
import time
import uuid
try:
    import handoffs,native,worker_interruption_recovery
except ImportError:
    from broker import handoffs,native,worker_interruption_recovery

SOURCE_SHA='3e8c3c5f0c422b3ae9c0a5b825288af60a0904ce6c4bf400db49ec68fd272c45'
VALIDATION_PENDING_SOURCE_SHA='67c222d0e0c4e1b205fc32eb0d04d8dd022ab5c60eb904b44eeade2cd82ff63b'
LEGACY_SOURCE_SHA='d911f64499a5ae44fd0c1583d2f3de092376933353ea1cbc856339e3a23ec718'
PROXY_IMAGE='sha256:55e34ae248147017aad74670c5e50a7f6e9c9783b3759f917459fe76bf456ddd'


def verify_proxy(b):
    info=b.docker('GET','/containers/'+b.PREFIX+'-model-proxy-1/json')
    labels=(info or {}).get('Config',{}).get('Labels',{})
    if (not info or info['Image']!=PROXY_IMAGE or not info.get('State',{}).get('Running')
            or labels.get('com.docker.compose.project')!=b.PREFIX
            or labels.get('com.docker.compose.service')!='model-proxy'):
        raise ValueError('owned fixed typed-recovery proxy required')


def rejection(b, execution):
    if str(uuid.UUID(execution))!=execution:raise ValueError('canonical execution required')
    path=b.STATE/'runtime-decision-rejections'/(execution+'.json')
    if path.is_symlink() or path.stat().st_size>16384:raise ValueError('bounded controller rejection receipt required')
    return json.loads(path.read_text())


def register(b,payload):
    if not isinstance(payload,dict) or set(payload)!={'issue_id','source_task','failed_task'}:
        raise ValueError('exact runtime transport identities required')
    for value in payload.values():
        if str(uuid.UUID(value))!=value:raise ValueError('canonical runtime transport identity required')
    if hashlib.sha256(Path(handoffs.__file__).read_bytes()).hexdigest() not in {SOURCE_SHA,LEGACY_SOURCE_SHA,VALIDATION_PENDING_SOURCE_SHA,'e4fd3719fab26bc5a3cc2ac2732fe0617e50f8e9dfdc77cbe039056ab029d1e9'}:
        raise ValueError('fixed source-pinned recovery transport required')
    issue,source,failed=(payload[k] for k in ('issue_id','source_task','failed_task'))
    with b.LOCK:
        with b.db() as c:
            c.execute('CREATE TABLE IF NOT EXISTS worker_recovery_transport_repairs(issue_id TEXT PRIMARY KEY,receipt TEXT)')
            old=c.execute('SELECT receipt FROM worker_recovery_transport_repairs WHERE issue_id=?',(issue,)).fetchone()
            if old:
                receipt=json.loads(old[0])
                if receipt['request']!=payload:raise ValueError('runtime transport replay already consumed')
                return receipt
            row=handoffs.load(c,source)
            route_row=c.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(issue,)).fetchone()
            if not row or not route_row:raise ValueError('existing recovery incident required')
            route,data=json.loads(route_row[0]),json.loads(row['data'])
            latest=c.execute('SELECT source_task FROM delivery_handoffs WHERE issue_id=? ORDER BY updated DESC LIMIT 1',(issue,)).fetchone()
            if (row['issue_id']!=issue or row['stage']!='technical_decision_required' or row['owner']!=route['cto']
                    or latest[0]!=source or not route.get('enabled') or route['author']==route['cto']
                    or data.get('source_status')!='failed' or data.get('source_failure_reason')!='agent_error.process_failure'
                    or data.get('error')!='recipient_execution_failed' or data.get('recipient_task')!=failed
                    or data.get('target')!=route['cto'] or data.get('failed_dispatch_stage')!='diagnose_cto'
                    or data.get('worker_interruption_recovery_used') or data.get('validation_failure')
                    or data.get('execution_repair') or data.get('worker_recovery_transport_repair')
                    or 'DELIVERY_WORKER_INTERRUPTION_RECOVERY_V1' not in data.get('instruction','')
                    or 'DELIVERY_TYPED_WORKER_RECOVERY_V1' in data.get('instruction','')
                    or not worker_interruption_recovery.qualified(c,issue,source,data)
                    or data['worker_interruption_recovery']['worker_image']!=b.IMAGE):
                raise ValueError('exact unused qualified runtime request failure required')
            if c.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone():
                raise ValueError('idle runtime transport replay required')
            bindings=c.execute('SELECT request_id,agent_id,issue_id FROM native_bindings WHERE task_id=?',(failed,)).fetchall()
            if len(bindings)!=1 or bindings[0]['agent_id']!=route['cto'] or bindings[0]['issue_id']!=issue:
                raise ValueError('exact CTO failure binding required')
            execution=bindings[0]['request_id']
        runs=native.issue_task_runs(json.loads((b.STATE/'native.json').read_text()),issue)
        authors=[r for r in runs if r.get('agent_id')==route['author']]
        recipient=next((r for r in runs if r['id']==failed),None)
        if (not authors or max(authors,key=lambda r:(r.get('created_at') or '',r['id']))['id']!=source
                or next(r for r in authors if r['id']==source).get('status')!='failed'
                or next(r for r in authors if r['id']==source).get('failure_reason')!='agent_error.process_failure'
                or not recipient or recipient.get('status')!='failed' or recipient.get('agent_id')!=route['cto']
                or recipient.get('wakeup_id')!=data.get('wakeup_id')
                or recipient.get('error')!='hermes provider error: API call failed after 1 retries'
                or any(r.get('status') in ('queued','dispatched','running') for r in runs)):
            raise ValueError('unchanged failed author and exact failed native CTO required')
        reject=rejection(b,execution);event=reject.get('event') or {}
        if (reject.get('operation')!='fixed_runtime_schema_truncation_v1' or reject.get('execution_id')!=execution
                or reject.get('author_retry_authorized') is not False or reject.get('delivery_approval') is not False
                or event.get('execution_id')!=execution or event.get('route')!='/api/v1/chat/completions'
                or event.get('status')!=502 or event.get('category')!='structured_decision_response_invalid'
                or event.get('finish_reason')!='length' or event.get('completion_tokens')!=8192
                or event.get('tool_count')!=0 or event.get('decision_schema')!='delivery_decision_v1'
                or event.get('strict_schema') is not True
                or event.get('structured_rejection_category')!='nonterminal_or_non_json_response'):
            raise ValueError('preserved exact plain JSON truncation required')
        verify_proxy(b)
        receipt=dict(request=payload,operation='typed_worker_recovery_transport_repair_v1',execution_id=execution,
                     rejection=reject,previous_handoff=dict(row),proxy_image=PROXY_IMAGE,
                     author_retry_authorized=False,delivery_approval=False,at=time.time())
        updated=dict(data,error='author_execution_failed',worker_recovery_transport_repair=receipt,
                     diagnostic_revision=source+':typed-runtime-request-v1',trigger_task=failed)
        for field in ('recipient_task','wakeup_id','dispatch_marker','dispatch_stage','dispatched_at',
                      'target','instruction','decision','control_error','control_error_count','alerted'):
            updated.pop(field,None)
        with b.db() as c:
            if dict(handoffs.load(c,source))!=dict(row):raise ValueError('runtime incident changed during qualification')
            if c.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone():
                raise ValueError('execution started during qualification')
            c.execute('INSERT INTO worker_recovery_transport_repairs VALUES (?,?)',(issue,json.dumps(receipt,sort_keys=True)))
            handoffs.save(c,source,issue,'diagnose_cto',route['cto'],updated,time.time())
        return receipt
