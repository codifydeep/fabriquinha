"""One CTO-only recovery after a proven controller ACP bound repair.

No author restart, test edits, Red receipt or delivery authority. A lost wakeup
acknowledgement is observed by its durable marker, never retried as a new POST.
"""
import hashlib
import json
import time
from pathlib import Path


def qualify(e):
    if not (e['enabled'] and e['test_first'] and e['author']!=e['cto']
            and e['actor']==e['cto'] and e['mode']=='planning'
            and e['task_issue']==e['issue'] and e['status']=='failed'
            and 'restricted broker stream failed: broker_internal' in e['error']
            and e['wakeup']==e['expected_wakeup'] and e['lease']=='closed'
            and e['active']==0 and not e['red'] and not e['pending']
            and sorted(e['events'])==[('initialize',1),('session/new',1)]
            and 12000<e['chars']<=32000 and e['qualified'] and e['client_rejected']
            and e['diagnostic'].get('kind')=='rejected_snapshot'
            and e['diagnostic'].get('category')=='new_test_syntax_error'):
        raise ValueError('verified pre-prompt CTO bound repair required')
    return dict(operation='cto_registered_prompt_bound_recovery_v1',
        source_task=e['source_task'],old_task=e['old_task'],old_wakeup=e['wakeup'],
        policy_sha256=e['policy_sha256'],prompt_chars=e['chars'],
        diagnostic_sha256=hashlib.sha256(json.dumps(e['diagnostic'],sort_keys=True).encode()).hexdigest(),
        previous_limit=12000,controller_limit=32000,client_limit=12000,
        author_retry_authorized=False,delivery_approval=False)


def dispatch(record,proof,save,wake,remaining,minimum):
    if record:
        if record['proof']!=proof:raise ValueError('consumed recovery proof drift')
        if record['state']=='accepted':return record
        # Intent was stored before the external effect. Unknown outcome is only
        # looked up, including after a restart; absence never authorizes a POST.
        allow_create=False
    else:
        if remaining<minimum:return None
        marker=hashlib.sha256(json.dumps(proof,sort_keys=True).encode()).hexdigest()
        record=dict(state='intent',proof=proof,marker=marker,at=time.time())
        save(record)
        allow_create=True
    result=wake(record['marker'],allow_create)
    if result:
        record=dict(record,state='accepted',wakeup_id=result['id'])
        save(record)
    return record


def recover(b,route,runs,source,prior,effects):
    """Controller hook, restricted to the exact failed pre-Red CTO execution."""
    if not prior or prior['stage'] not in ('diagnose_cto','test_first_blocked'):
        return False
    if source.get('status')!='completed' or source.get('agent_id')!=route.get('author'):
        return False
    data=json.loads(prior['data'])
    if data.get('phase')!='test_first' or data.get('error')!='test_first_cto_execution_failed':
        return False
    try:
        import native,handoffs,acp_transport
    except ImportError:
        from broker import native,handoffs,acp_transport
    with b.db() as con:
        con.execute('CREATE TABLE IF NOT EXISTS cto_prompt_bound_recoveries('
                    'source_task TEXT PRIMARY KEY,receipt TEXT)')
        stored=con.execute('SELECT receipt FROM cto_prompt_bound_recoveries WHERE source_task=?',
                           (source['id'],)).fetchone()
        # After acceptance, a second failed CTO remains blocked. No new proof
        # or image can reset the per-source attempt.
        record=json.loads(stored[0]) if stored else None
        if record and record['state']=='accepted':
            if data.get('test_first_cto_wakeup')==record['wakeup_id']:return False
            if (record['proof']['source_task']!=source['id']
                    or data.get('test_first_cto_wakeup')!=record['proof']['old_wakeup']):
                raise ValueError('accepted CTO recovery binding drift')
            # Crash after accepting the native wakeup but before handoff save:
            # restore only the pointer, without a second external operation.
            updated=dict(data,cto_prompt_bound_recovery=record,
                         test_first_cto_wakeup=record['wakeup_id'],dispatched_at=record['at'])
            handoffs.save(con,source['id'],route['issue_id'],'test_first_cto_diagnosis',
                          route['cto'],updated,time.time())
            return True
        candidates=[r for r in runs if r.get('agent_id')==route['cto']
                    and r.get('wakeup_id')==data.get('test_first_cto_wakeup')]
        if len(candidates)!=1:return False
        old=candidates[0]
        bindings=con.execute('SELECT n.request_id,l.status FROM native_bindings n '
            'JOIN leases l USING(request_id) WHERE n.task_id=? AND n.agent_id=? AND n.issue_id=?',
            (old['id'],route['cto'],route['issue_id'])).fetchall()
        if len(bindings)!=1:return False
        events=[tuple(r) for r in con.execute('SELECT method,success FROM acp_events WHERE request_id=?',
                                              (bindings[0]['request_id'],))]
        active=con.execute("SELECT count(*) FROM leases WHERE status IN ('creating','starting','running','active')").fetchone()[0]
        red=bool(con.execute('SELECT 1 FROM test_first_red WHERE issue_id=?',(route['issue_id'],)).fetchone())
    task=native.task_record(effects.settings,old['id'],route['cto'])
    issue=native.issue_record(effects.settings,route['issue_id'])
    binding=dict(task_id=task['id'],agent_id=task['agent_id'],issue_id=task.get('issue_id'),
                 wakeup_id=task.get('wakeup_id'),handoff_note=task.get('handoff_note'))
    frame=b.native_task_prompt(dict(jsonrpc='2.0',id=1,method='session/prompt',
        params=dict(sessionId='bound-proof',prompt=[dict(type='text',text='bound-proof')])),
        'planning',issue,binding)
    acp_transport.validate_frame(frame)
    client_rejected=False
    try:acp_transport.validate_frame(json.loads(json.dumps(frame)))
    except ValueError:client_rejected=True
    policy=hashlib.sha256(Path(b.native_task_prompt.__code__.co_filename).read_bytes()
                         +Path(acp_transport.__file__).read_bytes()).hexdigest()
    try:
        proof=qualify(dict(enabled=route.get('enabled'),test_first=route.get('test_first'),
            author=route['author'],cto=route['cto'],actor=task['agent_id'],
            issue=route['issue_id'],task_issue=task.get('issue_id'),
            mode=effects.settings['agents'].get(route['cto']),status=task['status'],
            error=task.get('error') or '',wakeup=task.get('wakeup_id'),
            expected_wakeup=data.get('test_first_cto_wakeup'),lease=bindings[0]['status'],
            active=active,red=red,events=events,
            pending=any(r['status'] in ('queued','dispatched','running') for r in runs),
            chars=sum(len(p['text']) for p in frame['params']['prompt']),
            qualified=type(frame) is acp_transport.ControllerPrompt,client_rejected=client_rejected,
            diagnostic=data.get('diagnostic') or {},source_task=source['id'],old_task=old['id'],policy_sha256=policy))
    except ValueError:return False
    def save(receipt):
        with b.db() as con:
            con.execute('INSERT INTO cto_prompt_bound_recoveries VALUES (?,?) '
                'ON CONFLICT(source_task) DO UPDATE SET receipt=excluded.receipt',
                (source['id'],json.dumps(receipt,sort_keys=True)))
            con.commit()
    instruction=('CONTROLLER TEST-FIRST TECHNICAL INCIDENT. The previous CTO session failed '
        'before prompt/model execution due to the controller ACP bound; the registered prompt '
        'now passes the repaired bound while client bounds are unchanged. ONE diagnosis recovery. '
        'No Red exists. Diagnose the original rejected tests-only snapshot: '
        +json.dumps(data['diagnostic'],sort_keys=True)+'. Only the original author may correct '
        'the declared NEW test and run the full pinned suite. Product and pre-existing tests '
        'remain immutable. Return only JSON with action (request_correction or escalate_cto), '
        'reason (one concrete sentence, at most 1200 characters), optional_files ([]). '
        'No file edits, weakening coverage, fabricated Red, CEO technical question or delivery approval. '
        '\nDELIVERY_STRUCTURED_DECISION_V1:technical\nDELIVERY_TYPED_DECISION_V1\n'
        'DELIVERY_TECHNICAL_LENGTH_FEEDBACK_V1\n')
    result=dispatch(record,proof,save,lambda marker,allow_create:effects.ensure_wakeup(
        route['issue_id'],route['cto'],source['id'],marker,instruction,allow_create=allow_create),
        effects.remaining_calls(),route['minimum_calls'])
    if result and result['state']=='accepted':
        updated=dict(data,cto_prompt_bound_recovery=result,
                     test_first_cto_wakeup=result['wakeup_id'],dispatched_at=time.time())
        with b.db() as con:
            handoffs.save(con,source['id'],route['issue_id'],'test_first_cto_diagnosis',
                          route['cto'],updated,time.time())
    elif result and time.time()-result['at']>=1800:
        updated=dict(data,cto_prompt_bound_recovery=result,
                     error='cto_prompt_bound_recovery_outcome_unconfirmed',
                     required_action='CTO inspect durable wakeup marker; do not repeat POST')
        with b.db() as con:
            handoffs.save(con,source['id'],route['issue_id'],'test_first_blocked',
                          route['cto'],updated,time.time())
    return True
