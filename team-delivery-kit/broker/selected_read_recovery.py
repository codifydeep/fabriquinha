"""Once-per-issue changed-contract recovery for an observed rejected read.

Controller-only: consumes actual proxy evidence, preserved bytes and the original
independent CTO sponsorship. No new Red, approval or generic worker privilege.
"""
import hashlib
import json
import time
import uuid


def rejected_read(b, execution):
    name=b.PREFIX+'-model-proxy-1'
    proxy=b.docker('GET','/containers/'+name+'/json')
    if (not proxy.get('State',{}).get('Running')
            or proxy.get('Config',{}).get('Labels',{}).get('com.docker.compose.project')!=b.PREFIX):
        raise ValueError('scoped running proxy required')
    events=[]
    for line in b.docker_stdout(name,limit=1048576).splitlines():
        try:event=json.loads(line)
        except (ValueError,TypeError):continue
        if (isinstance(event,dict) and event.get('event')=='model_proxy_request'
                and event.get('execution_id')==execution and event.get('status')==502
                and event.get('artifact_selected_tool')=='read_file'
                and event.get('artifact_rejection_category')=='invalid_forced_argument'
                and type(event.get('call_number')) is int):events.append(event)
    if len(events)!=1:raise ValueError('unique observed rejected selected read required')
    return dict(execution_id=execution,call_number=events[0]['call_number'],
                category='invalid_forced_argument')


def register(b,payload):
    try:import native,handoffs,handoff_runtime,artifact_transport_recovery
    except ImportError:from broker import native,handoffs,handoff_runtime,artifact_transport_recovery
    if not isinstance(payload,dict) or set(payload)!={'issue_id','source_task','cto_task'}:
        raise ValueError('exact selected-read recovery identity required')
    for value in payload.values():
        if str(uuid.UUID(value))!=value:raise ValueError('invalid selected-read recovery identity')
    with b.LOCK:
        with b.db() as c:
            c.execute('CREATE TABLE IF NOT EXISTS selected_read_recoveries(issue_id TEXT PRIMARY KEY,receipt TEXT)')
            old=c.execute('SELECT receipt FROM selected_read_recoveries WHERE issue_id=?',(payload['issue_id'],)).fetchone()
            if old:
                receipt=json.loads(old[0])
                if receipt['request']!=payload:raise ValueError('selected-read recovery already consumed')
                return receipt
            row=handoffs.load(c,payload['source_task'])
            if not row or row['issue_id']!=payload['issue_id']:raise ValueError('blocked source missing')
            data=json.loads(row['data'])
            route=json.loads(c.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(payload['issue_id'],)).fetchone()[0])
            if (row['stage']!='test_first_blocked' or not route.get('enabled') or not route.get('test_first')
                    or route['author']==route['cto'] or len(route['test_first_files'])!=1):
                raise ValueError('current blocked tests-only source required')
            if c.execute('SELECT 1 FROM test_first_red WHERE issue_id=?',(payload['issue_id'],)).fetchone():
                raise ValueError('Red already exists')
            if c.execute("SELECT 1 FROM leases WHERE status IN ('running','creating','starting','active')").fetchone():
                raise ValueError('idle read-contract recovery required')
            bindings=c.execute('SELECT n.request_id,l.status FROM native_bindings n JOIN leases l USING(request_id) WHERE n.task_id=?',
                               (payload['source_task'],)).fetchall()
            if len(bindings)!=1 or bindings[0]['status']!='closed':raise ValueError('closed execution required')
            execution=bindings[0]['request_id']
            if c.execute('SELECT coalesce(sum(tool_count),0) FROM tool_events WHERE request_id=?',(execution,)).fetchone()[0]!=0:
                raise ValueError('pretool read failure only')
            sponsors=[json.loads(r[0]) for r in c.execute('SELECT data FROM delivery_handoffs WHERE issue_id=?',(payload['issue_id'],))]
        if '\nDELIVERY_DETERMINISTIC_READ_V1\n' not in b.test_artifact_phase_context(payload['issue_id'],route['author']):
            raise ValueError('installed changed selected-read contract required')
        settings=json.loads((b.STATE/'native.json').read_text())
        runs=native.issue_task_runs(settings,payload['issue_id'])
        authors=[r for r in runs if r.get('agent_id')==route['author']]
        source=next((r for r in authors if r['id']==payload['source_task']),{})
        cto=next((r for r in runs if r['id']==payload['cto_task']),{})
        if (not authors or max(authors,key=lambda r:(r.get('created_at') or '',r['id']))['id']!=source.get('id')
                or source.get('status')!='failed' or cto.get('status')!='completed'
                or cto.get('agent_id')!=route['cto'] or not source.get('wakeup_id')
                or any(r.get('status') in ('queued','dispatched','running') for r in runs)):
            raise ValueError('latest idle failed author and independent CTO required')
        sponsors=[d for d in sponsors if d.get('cto_task')==cto['id']
                  and d.get('test_first_cto_wakeup')==cto.get('wakeup_id')
                  and d.get('test_first_correction_wakeup')==source['wakeup_id']]
        decision=handoff_runtime.Effects(b,settings).decision(cto)
        if (len(sponsors)!=1 or sponsors[0].get('decision')!=decision
                or decision.get('action')!='request_correction' or decision.get('optional_files')!=[]):
            raise ValueError('exact existing CTO correction sponsorship required')
        event=rejected_read(b,execution)
        proof=artifact_transport_recovery.verify_preserved_failure(b,source['id'],
            {'files':{route['test_first_files'][0]:hashlib.sha256(b'').hexdigest()}})
        if not proof.get('verified') or not proof.get('baseline_unchanged'):raise ValueError('unchanged empty workspace required')
        receipt=dict(request=payload,decision=decision,proof=proof,proxy_event=event,
            previous_blocker=data,operation='controller_selected_read_recovery_v1',at=time.time(),delivery_approval=False)
        with b.db() as c:
            if dict(handoffs.load(c,source['id']))!=dict(row):raise ValueError('blocked source changed')
            c.execute('INSERT INTO selected_read_recoveries VALUES (?,?)',(payload['issue_id'],json.dumps(receipt,sort_keys=True)))
            updated=dict(data,selected_read_recovery=receipt)
            handoffs.save(c,source['id'],payload['issue_id'],'test_first_selected_read_recovery_pending',route['author'],updated,time.time())
        return receipt
