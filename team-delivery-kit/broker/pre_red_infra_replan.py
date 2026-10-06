"""Controller-only, once-per-issue pre-Red infrastructure diagnosis.

Never grants implementation, manufactures Red, or retries an author directly.
Host-awake protection is an operational precondition, not a delivery receipt.
"""
import hashlib
import json
import time
import uuid


def initialize(con):
    con.execute('CREATE TABLE IF NOT EXISTS pre_red_infra_replans('
                'issue_id TEXT PRIMARY KEY,source_task TEXT,receipt TEXT)')


def qualified(con, issue, source, data):
    if not con.execute("SELECT 1 FROM sqlite_master WHERE name='pre_red_infra_replans'").fetchone():
        return False
    row=con.execute('SELECT source_task,receipt FROM pre_red_infra_replans WHERE issue_id=?',(issue,)).fetchone()
    return bool(row and row[0]==source and json.loads(row[1])==data.get('infrastructure_replan'))


def register(b, payload):
    try:
        import native,handoffs,handoff_runtime,artifact_transport_recovery
    except ImportError:
        from broker import native,handoffs,handoff_runtime,artifact_transport_recovery
    if not isinstance(payload,dict) or set(payload)!={'issue_id','source_task','cto_task'}:
        raise ValueError('exact infrastructure replan identity required')
    for value in payload.values():
        if str(uuid.UUID(value))!=value:raise ValueError('invalid infrastructure replan identity')
    with b.LOCK:
        with b.db() as con:
            initialize(con)
            old=con.execute('SELECT receipt FROM pre_red_infra_replans WHERE issue_id=?',(payload['issue_id'],)).fetchone()
            if old:
                receipt=json.loads(old[0])
                if receipt['request']!=payload:raise ValueError('infrastructure replan already consumed')
                return receipt
            row=handoffs.load(con,payload['source_task'])
            if not row or row['issue_id']!=payload['issue_id']:raise ValueError('blocked source missing')
            data=json.loads(row['data'])
            route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(payload['issue_id'],)).fetchone()[0])
            if (row['stage']!='test_first_blocked' or data.get('error')!='test_first_cto_requires_replanning'
                    or data.get('blocked_cause')!='test_author_execution_failed'
                    or data.get('cto_task')!=payload['cto_task'] or not route.get('test_first')
                    or not route.get('enabled') or route['author']==route['cto']
                    or len(route['test_first_files'])!=1):raise ValueError('current escalated pre-Red source required')
            if con.execute('SELECT 1 FROM test_first_red WHERE issue_id=?',(payload['issue_id'],)).fetchone():
                raise ValueError('Red already exists')
            if con.execute("SELECT 1 FROM leases WHERE status IN ('running','creating','starting','active')").fetchone():
                raise ValueError('idle infrastructure diagnosis required')
            binding=con.execute('SELECT n.request_id,l.status FROM native_bindings n JOIN leases l USING(request_id) WHERE n.task_id=?',
                                (payload['source_task'],)).fetchall()
            if len(binding)!=1 or binding[0]['status'] not in ('expired','closed'):
                raise ValueError('exact terminated execution required')
            if con.execute('SELECT coalesce(sum(tool_count),0) FROM tool_events WHERE request_id=?',
                           (binding[0]['request_id'],)).fetchone()[0]!=0:raise ValueError('pretool diagnosis only')
        settings=json.loads((b.STATE/'native.json').read_text())
        runs=native.issue_task_runs(settings,payload['issue_id'])
        authors=[r for r in runs if r.get('agent_id')==route['author']]
        source=next((r for r in authors if r['id']==payload['source_task']),{})
        cto=next((r for r in runs if r['id']==payload['cto_task']),{})
        if (not authors or max(authors,key=lambda r:(r.get('created_at') or '',r['id']))['id']!=source.get('id')
                or source.get('status')!='failed' or cto.get('status')!='completed'
                or cto.get('agent_id')!=route['cto'] or cto.get('wakeup_id')!=data.get('test_first_cto_wakeup')
                or any(r.get('status') in ('queued','dispatched','running') for r in runs)):
            raise ValueError('latest idle author and exact independent CTO required')
        presentation=None
        if binding[0]['status']=='closed':
            from generated_context import compact
            if 'restricted broker stream failed: native_prompt_bounds' not in (source.get('error') or ''):
                raise ValueError('closed execution requires exact pre-model prompt-bound failure')
            description=native.issue_record(settings,payload['issue_id'])['description']
            effective,presentation=compact(description)
            if not presentation or len(effective)>4000:
                raise ValueError('verified bounded generated context presentation required')
        decision=handoff_runtime.Effects(b,settings).decision(cto)
        if decision!=data.get('decision') or decision.get('action')!='escalate_cto' or decision.get('optional_files')!=[]:
            raise ValueError('actual prior CTO escalation required')
        proof=artifact_transport_recovery.verify_preserved_failure(b,source['id'],
            {'files':{route['test_first_files'][0]:hashlib.sha256(b'').hexdigest()}})
        if not proof.get('verified') or not proof.get('baseline_unchanged'):raise ValueError('unchanged empty workspace required')
        receipt=dict(request=payload,proof=proof,worker_image=b.IMAGE,
            operation='preserved_pretool_infrastructure_diagnosis_v1',
            previous_blocker=data,at=time.time(),author_retry_authorized=False)
        if presentation:receipt['prompt_presentation']=presentation
        updated=dict(data,infrastructure_replan=receipt,
            diagnostic=dict(kind='preserved_pretool_infrastructure',task_id=source['id'],
                issue_id=payload['issue_id'],manifest_sha256=proof['manifest_sha256'],
                baseline_unchanged=True,new_test_empty=True,accepted_tools=0),
            error='pre_red_infrastructure_diagnosis_required')
        if presentation:
            updated['diagnostic'].update(category='native_prompt_bounds',
                tests_executed=False,red_verified=False,delivery_approval=False,
                prompt_presentation=presentation,
                next_action='CTO independently decide tests-only restart after verified context repair')
        for key in ('cto_task','decision','test_first_cto_wakeup','dispatched_at'):updated.pop(key,None)
        with b.db() as con:
            # Revalidate before committing; publication/wakeup remains outside transaction.
            if dict(handoffs.load(con,source['id']))!=dict(row):raise ValueError('blocked source changed during qualification')
            con.execute('INSERT INTO pre_red_infra_replans VALUES (?,?,?)',
                        (payload['issue_id'],source['id'],json.dumps(receipt,sort_keys=True)))
            handoffs.save(con,source['id'],payload['issue_id'],'technical_decision_required',route['cto'],updated,time.time())
        return receipt
