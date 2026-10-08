"""One new read-only observation after sealed controller maintenance.

The old transport outcome remains UNKNOWN. This is not evidence of zero model
calls and never reopens its capability, container or session. Only a separate
CTO observation of the exact frozen artifacts can be scheduled. Operator-only.
"""
import hashlib
import json
from pathlib import Path
import time
import uuid
try:
    import controller_maintenance as maintenance, handoffs, native, test_revision_review
except ImportError:
    from broker import controller_maintenance as maintenance, handoffs, native, test_revision_review

SERVER_SHA = 'cdedbb64664595dbc99b54d16d070465d58c0bc3d6ceb2c3ea50120a62fcbde5'


def qualify(e):
    if not (e['maintenance'].get('stage') == 'sealed'
            and e['maintenance'].get('drained') is True
            and e['maintenance'].get('namespace') == e['namespace']
            and e['server_sha256'] == SERVER_SHA
            and e['stage'] == 'technical_decision_required'
            and e['owner'] == e['cto'] == e['actor']
            and e['mode'] == 'planning' and e['author'] != e['cto']
            and e['enabled'] is True and e['status'] == 'failed'
            and e['wakeup'] == e['expected_wakeup'] and bool(e['wakeup'])
            and e['lease'] == 'interrupted'
            and e['startup'].get('stage') == 'failed'
            and e['startup'].get('category') == 'startup_transport_outcome_unknown'
            and e['data'].get('error') == 'recipient_execution_failed'
            and e['data'].get('failed_dispatch_stage') == 'diagnose_cto'
            and e['data'].get('recipient_task') == e['failed_task']
            and e['data'].get('target') == e['cto']
            and e['data'].get('artifact_diagnosis') is True
            and e['data'].get('validation_failure', {}).get('source_task') == e['source_task']
            and e['data'].get('unsupported_experiment_recovery', {}).get('attempt_limit') == 1
            and e['data'].get('unsupported_experiment_recovery', {}).get('test_edits_authorized') is False
            and e['native_active'] == 0 and e['active_leases'] == 0
            and not e['old_container_exists'] and not e['prior_recovery']
            and len(e['mounts']) == 2
            and {m['Target'] for m in e['mounts']} == {'/evidence/candidate', '/evidence/previous'}
            and all(m.get('ReadOnly') is True for m in e['mounts'])):
        raise ValueError('sealed independent interrupted diagnosis required')
    return dict(operation='new_readonly_diagnosis_after_maintenance_v1',
        maintenance_operation=e['maintenance']['operation_id'], old_task=e['failed_task'],
        old_request=e['request_id'], old_outcome='unknown', old_capability_reused=False,
        extra_observation_limit=1, artifact_mounts=e['mounts'],
        validation_failure_sha256=hashlib.sha256(json.dumps(
            e['data']['validation_failure'], sort_keys=True).encode()).hexdigest(),
        author_retry_authorized=False, test_edits_authorized=False,
        experiment_retry_authorized=False, delivery_approval=False)


def register(b, payload):
    if not isinstance(payload, dict) or set(payload) != {'source_task', 'failed_task', 'maintenance_operation'}:
        raise ValueError('exact observation recovery identity required')
    for value in payload.values():
        if str(uuid.UUID(value)) != value: raise ValueError('canonical identity required')
    source, failed = payload['source_task'], payload['failed_task']
    with b.LOCK, b.db() as con:
        con.execute('CREATE TABLE IF NOT EXISTS diagnostic_maintenance_recoveries('
                    'source_task TEXT PRIMARY KEY,receipt TEXT)')
        old = con.execute('SELECT receipt FROM diagnostic_maintenance_recoveries WHERE source_task=?', (source,)).fetchone()
        if old:
            receipt = json.loads(old[0])
            if receipt['request'] != payload: raise ValueError('observation recovery already consumed')
            return receipt  # Observe the same intent; never schedule again.
        row = handoffs.load(con, source)
        if not row: raise ValueError('existing frozen incident required')
        data = json.loads(row['data'])
        route = json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?', (row['issue_id'],)).fetchone()[0])
        latest = con.execute('SELECT source_task FROM delivery_handoffs WHERE issue_id=? ORDER BY updated DESC LIMIT 1', (row['issue_id'],)).fetchone()
        bindings = con.execute('SELECT n.*,l.status,l.name FROM native_bindings n JOIN leases l USING(request_id) WHERE n.task_id=?', (failed,)).fetchall()
        if (latest[0] != source or len(bindings) != 1 or bindings[0]['agent_id'] != route['cto']
                or bindings[0]['issue_id'] != row['issue_id']):
            raise ValueError('exact latest independent CTO binding required')
        binding = dict(bindings[0])
        startup = con.execute('SELECT state FROM acp_startups WHERE request_id=?', (binding['request_id'],)).fetchone()
        state = maintenance.current(con)
        if not state or state['operation_id'] != payload['maintenance_operation']:
            raise ValueError('exact sealed maintenance identity required')
        settings = json.loads((b.STATE / 'native.json').read_text())
        task = native.task_record(settings, failed, route['cto'])
        if task.get('id') != failed or task.get('issue_id') != row['issue_id']:
            raise ValueError('exact native diagnostic task required')
        mounts = test_revision_review.diagnostic_mounts(b, {'issue_id':row['issue_id'], 'agent_id':route['cto']})
        proof = qualify(dict(maintenance=state, namespace=b.PREFIX,
            server_sha256=hashlib.sha256(Path(b.__file__).read_bytes()).hexdigest(),
            stage=row['stage'], owner=row['owner'], cto=route['cto'], author=route['author'],
            actor=task.get('agent_id'), mode=settings['agents'].get(route['cto']),
            enabled=route.get('enabled'), status=task.get('status'), wakeup=task.get('wakeup_id'),
            expected_wakeup=data.get('wakeup_id'), lease=binding['status'],
            startup=json.loads(startup[0]) if startup else {}, data=data,
            failed_task=failed, source_task=source, request_id=binding['request_id'],
            native_active=len(maintenance.native_active(b)),
            active_leases=con.execute("SELECT count(*) FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone()[0],
            old_container_exists=bool(b.docker('GET','/containers/'+binding['name']+'/json')),
            prior_recovery=data.get('diagnostic_maintenance_recovery'), mounts=mounts))
        receipt = dict(proof, request=payload, previous_handoff=dict(row), at=time.time())
        updated = dict(data, diagnostic_maintenance_recovery=proof,
            diagnostic_revision=data.get('diagnostic_revision','')+':maintenance:'+state['operation_id'],
            trigger_task=failed, target=route['cto'],
            required_action='CTO observe same frozen failure after maintenance; old transport remains unknown')
        for key in ('wakeup_id','recipient_task','dispatch_marker','dispatch_stage','dispatched_at',
                    'instruction','decision','control_error','control_error_count','alerted'):
            updated.pop(key, None)
        con.execute('INSERT INTO diagnostic_maintenance_recoveries VALUES (?,?)', (source,json.dumps(receipt,sort_keys=True)))
        handoffs.save(con,source,row['issue_id'],'diagnose_cto',route['cto'],updated,time.time())
        return receipt
