"""Operator-only financial/access recovery, never a worker or delivery approval.

The operator verifies the official provider balance and key limit, archives the
exact proxy pause, then supplies its non-secret resolution receipt under sealed
maintenance. Only an interrupted CTO diagnosis is resumed. Partial author work
must pass the existing immutable failed-execution diagnostic path first.
"""
import json
import time
import uuid
try:
    import controller_maintenance as maintenance, handoffs, native, failed_execution_diagnosis
except ImportError:
    from broker import controller_maintenance as maintenance, handoffs, native, failed_execution_diagnosis

ACTIVE = ('queued', 'dispatched', 'running')
ERROR = 'hermes session/prompt failed: session/prompt: Internal error (code=-32603, data={"broker_diagnostic": ["provider_configuration"]})'


def qualify(row, route, data, runs, bindings, resolution):
    if (resolution.get('operation') != 'operator_provider_access_resolution_v1'
            or resolution.get('delivery_approval') is not False
            or resolution.get('calls_before') != resolution.get('calls_after')
            or type(resolution.get('calls_before')) is not int
            or resolution['calls_before'] < 1
            or resolution.get('account_balance_positive') is not True
            or resolution.get('key_remaining_positive') is not True
            or resolution.get('pause', {}).get('upstream_status') not in (401, 402, 403)
            or resolution['pause'].get('call_number') != resolution['calls_before']):
        raise ValueError('verified unchanged-counter operator resolution required')
    if str(uuid.UUID(resolution['operation_id'])) != resolution['operation_id']:
        raise ValueError('canonical provider resolution identity required')
    authors = [r for r in runs if r.get('agent_id') == route['author']]
    source = next((r for r in runs if r['id'] == row['source_task']), None)
    recipients = [r for r in runs if r.get('wakeup_id') == data.get('wakeup_id')
                  and r.get('agent_id') == route['cto'] and data.get('wakeup_id')]
    if (row['stage'] not in ('awaiting_acceptance', 'accepted', 'technical_decision_required')
            or row['owner'] != route['cto'] or route['author'] == route['cto']
            or data.get('contract_sha256') != route['contract_sha256']
            or data.get('source_status') != 'failed'
            or data.get('source_failure_reason') != 'agent_error.provider_server_error'
            or data.get('error') != 'recipient_execution_failed'
            or data.get('target') != route['cto'] or data.get('dispatch_stage') != 'diagnose_cto'
            or not source or source.get('status') != 'failed' or source.get('error') != ERROR
            or not authors or max(authors, key=lambda r:(r.get('created_at') or '',r['id']))['id'] != source['id']
            or len(recipients) != 1 or recipients[0].get('status') != 'failed'
            or recipients[0].get('error') != ERROR
            or recipients[0].get('failure_reason') != 'agent_error.provider_server_error'
            or any(r.get('status') in ACTIVE for r in runs)
            or len(bindings) != 1 or bindings[0]['status'] != 'closed'
            or bindings[0]['mode'] != 'implementation'
            or data.get('evidence') or data.get('review') or data.get('validation_failure')):
        raise ValueError('exact idle provider-interrupted author and CTO required')
    return recipients[0]['id']


def register(b, payload):
    if not isinstance(payload, dict) or set(payload) != {'source_task', 'resolution'}:
        raise ValueError('exact operator recovery payload required')
    source, resolution = payload['source_task'], payload['resolution']
    if str(uuid.UUID(source)) != source:
        raise ValueError('canonical source required')
    with b.LOCK, b.db() as con:
        barrier = maintenance.current(con)
        if not barrier or barrier['stage'] != 'sealed' or barrier.get('drained') is not True:
            raise ValueError('sealed drained maintenance required')
        if con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone():
            raise ValueError('idle provider recovery required')
        con.execute('CREATE TABLE IF NOT EXISTS provider_access_recoveries(source_task TEXT PRIMARY KEY,receipt TEXT)')
        old = con.execute('SELECT receipt FROM provider_access_recoveries WHERE source_task=?',(source,)).fetchone()
        if old:
            receipt = json.loads(old[0])
            if receipt['request'] != payload:
                raise ValueError('provider resolution replay drift')
            row = handoffs.load(con, source)
            current_route = json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(row['issue_id'],)).fetchone()[0])
            done = con.execute('SELECT receipt FROM failed_execution_diagnoses WHERE source_task=?',(source,)).fetchone()
            if done and current_route == receipt['previous_route']:
                diagnostic = json.loads(done[0])
                return dict(source_task=source,stage=row['stage'],diagnostic_only=True,
                    author_restarted=False,delivery_approval=False,volume=diagnostic['volume'])
        else:
            row = handoffs.load(con, source)
            if not row: raise ValueError('preserved incident required')
            route = json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(row['issue_id'],)).fetchone()[0])
            latest = con.execute('SELECT source_task FROM delivery_handoffs WHERE issue_id=? ORDER BY updated DESC LIMIT 1',(row['issue_id'],)).fetchone()
            if latest[0] != source or not route.get('enabled'):
                raise ValueError('current enabled incident required')
            data = json.loads(row['data'])
            bindings = con.execute('SELECT l.status,g.mode FROM native_bindings n JOIN leases l USING(request_id) JOIN grants g USING(request_id) WHERE n.task_id=?',(source,)).fetchall()
            settings = json.loads((b.STATE/'native.json').read_text())
            runs = native.issue_task_runs(settings,row['issue_id'])
            recipient = qualify(row,route,data,runs,bindings,resolution)
            snapshot = con.execute('SELECT status FROM failed_execution_snapshots WHERE task_id=?',(source,)).fetchone()
            if not snapshot or snapshot['status'] != 'complete':
                raise ValueError('preserved failed-work snapshot required')
            receipt = dict(request=payload,previous_handoff=dict(row),previous_route=route,
                recipient_task=recipient,maintenance_operation=barrier['operation_id'],
                author_restarted=False,delivery_approval=False,at=time.time())
            con.execute('INSERT INTO provider_access_recoveries VALUES(?,?)',(source,json.dumps(receipt,sort_keys=True)))
            route = dict(route,enabled=False)
            con.execute('UPDATE delivery_routes SET config=? WHERE issue_id=?',(json.dumps(route),row['issue_id']))
            data.update(error='author_execution_failed',provider_access_resolution=resolution)
            handoffs.save(con,source,row['issue_id'],'technical_decision_required',route['cto'],data,time.time())
    # Reuses actual Red hashes and fixed frozen-suite validation; does not infer
    # a functional failure from a provider failure. Safe to resume after a crash.
    signature = json.loads(receipt['previous_handoff']['data'])['failure_signature']
    diagnostic = failed_execution_diagnosis.register(b,dict(source_task=source,failure_signature=signature))
    with b.LOCK, b.db() as con:
        row = handoffs.load(con,source)
        if row['stage'] != 'diagnose_cto':
            raise ValueError('diagnostic transition changed; keep route paused')
        current = json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(row['issue_id'],)).fetchone()[0])
        expected = dict(receipt['previous_route'],enabled=False)
        if current != expected:
            raise ValueError('route changed; keep provider recovery blocked')
        con.execute('UPDATE delivery_routes SET config=? WHERE issue_id=?',(json.dumps(receipt['previous_route']),row['issue_id']))
    return dict(source_task=source,stage='diagnose_cto',diagnostic_only=True,
                author_restarted=False,delivery_approval=False,volume=diagnostic['volume'])
