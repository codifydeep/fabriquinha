"""Maintenance-only observation recovery; never restart a completed author."""
import json
import time
import uuid
try:
    import controller_maintenance as maintenance, native
    from test_first_job import digest
except ImportError:
    from broker import controller_maintenance as maintenance, native
    from broker.test_first_job import digest


def eligible(route, data, source, runs, snapshot, bindings):
    authors=[r for r in runs if r.get('agent_id')==route['author']]
    if (not authors or max(authors,key=lambda r:(r.get('created_at') or '',r['id']))['id']!=source['id']
            or source.get('status')!='completed' or source.get('issue_id')!=route['issue_id']
            or source.get('agent_id')!=route['author'] or source.get('error')
            or any(r.get('status') in ('queued','dispatched','running') for r in runs)
            or data.get('contract_sha256')!=route['contract_sha256']
            or data.get('source_status')!='completed' or data.get('error_type')!='DockerOperationTimeout'
            or data.get('error')!='Docker operation deadline' or data.get('validation_failure')
            or data.get('evidence') or not snapshot or snapshot['status']!='complete'
            or len(bindings)!=1 or bindings[0]['status']!='closed' or bindings[0]['mode']!='implementation'):
        raise ValueError('exact completed immutable infrastructure failure required')


def resume(b, task):
    if str(uuid.UUID(task))!=task:raise ValueError('canonical source task required')
    with b.LOCK,b.db() as con:
        barrier=maintenance.current(con)
        if not barrier or barrier.get('stage')!='sealed' or barrier.get('drained') is not True:
            raise ValueError('sealed drained maintenance required')
        con.execute('CREATE TABLE IF NOT EXISTS validation_recoveries(source_task TEXT PRIMARY KEY,receipt TEXT)')
        old=con.execute('SELECT receipt FROM validation_recoveries WHERE source_task=?',(task,)).fetchone()
        if old:return json.loads(old[0])
        if con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone():
            raise ValueError('idle validation recovery required')
        row=con.execute('SELECT * FROM delivery_handoffs WHERE source_task=?',(task,)).fetchone()
        if not row or row['stage'] not in ('diagnose','diagnose_cto','awaiting_acceptance','accepted','technical_decision_required'):
            raise ValueError('preserved infrastructure handoff required')
        data=json.loads(row['data'])
        route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(row['issue_id'],)).fetchone()[0])
        snapshot=con.execute('SELECT volume,status FROM snapshots WHERE task_id=?',(task,)).fetchone()
        bindings=con.execute('SELECT l.status,g.mode FROM native_bindings n JOIN leases l USING(request_id) '
                            'JOIN grants g USING(request_id) WHERE n.task_id=?',(task,)).fetchall()
        settings=json.loads((b.STATE/'native.json').read_text())
        source=native.task_record(settings,task,route['author'])
        runs=native.issue_task_runs(settings,row['issue_id'])
        eligible(route,data,source,runs,snapshot,bindings)
        info=b.docker('GET','/volumes/'+snapshot['volume']) or {}
        labels=info.get('Labels',{})
        if labels.get('delivery-kit.owner')!=b.OWNER or labels.get('delivery-kit.source-task')!=task:
            raise ValueError('owned preserved snapshot required')
        receipt=dict(operation='durable_validation_observation_recovery_v1',previous_handoff=dict(row),
            route_sha256=digest(route),snapshot_volume=snapshot['volume'],maintenance_operation=barrier['operation_id'],
            author_restarted=False,delivery_approved=False,release_homologated=False,at=time.time())
        con.execute('INSERT INTO validation_recoveries VALUES(?,?)',(task,json.dumps(receipt,sort_keys=True)))
        # Retain all superseded diagnosis in the receipt, not as active dispatch.
        fresh={k:data[k] for k in ('source_task','contract_sha256','author','reviewer','attempts','phase_evidence') if k in data}
        fresh['validation_recovery']=dict(operation=receipt['operation'],receipt_sha256=digest(receipt))
        con.execute('UPDATE delivery_handoffs SET stage=?,owner=?,data=?,updated=? WHERE source_task=?',
                    ('validation_pending',route['reviewer'],json.dumps(fresh,sort_keys=True),time.time(),task))
        return receipt
