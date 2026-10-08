"""Controller-only, once-per-distinct-failure independent technical diagnosis.

Evidence identity is not retry identity: task/call IDs and size counts cannot
rearm an identical constraint failure. Unknown constraints forbid author retry.
"""
import hashlib
import json
import re


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()


def claim(c,issue,source,diagnostic):
    from artifact_rejection_receipts import from_event
    d=diagnostic
    if (d.get('issue_id')!=issue or d.get('task_id')!=source
            or d.get('kind')!='rejected_forced_tool_response'
            or d.get('operation')!='rejected_forced_tool_response_v1'
            or d.get('category')!='invalid_forced_argument'
            or d.get('provenance') not in ('owned_proxy_validator_log','owned_proxy_durable_validator_receipt')
            or not re.fullmatch(r'sha256:[a-f0-9]{64}',str(d.get('proxy_image')))):
        raise ValueError('exact controller-owned argument rejection required')
    canonical=from_event(dict(event='model_proxy_request',status=502,
        artifact_contract_present=True,artifact_selected_tool=d.get('tool'),
        artifact_rejection_category=d['category'],execution_id=d.get('execution_id'),
        call_number=d.get('call_number'),artifact_rejection_diagnostic=d.get('structure')))
    if not canonical or any(d.get(k)!=v for k,v in canonical.items()):
        raise ValueError('nonapproving canonical validator receipt required')
    shape=d.get('structure') or {}
    fingerprint=digest(dict(category=d['category'],tool=d['tool'],
        field=shape.get('field'),constraint=shape.get('constraint')))
    c.execute('CREATE TABLE IF NOT EXISTS verified_tool_incidents('
        'issue_id TEXT,source_task TEXT,fingerprint TEXT,receipt TEXT,'
        'PRIMARY KEY(issue_id,source_task),UNIQUE(issue_id,fingerprint))')
    old=c.execute('SELECT receipt FROM verified_tool_incidents WHERE issue_id=? AND source_task=?',
        (issue,source)).fetchone()
    if old:
        receipt=json.loads(old[0])
        if receipt['diagnostic_sha256']!=digest(d):raise ValueError('incident evidence drift')
        return receipt
    if (c.execute('SELECT 1 FROM verified_tool_incidents WHERE issue_id=? AND fingerprint=?',
            (issue,fingerprint)).fetchone()
            or c.execute('SELECT count(*) FROM verified_tool_incidents WHERE issue_id=?',(issue,)).fetchone()[0]>=2):
        return None
    receipt=dict(operation='verified_tool_incident_v1',issue_id=issue,source_task=source,
        fingerprint=fingerprint,diagnostic_sha256=digest(d),cause_known=bool(shape),
        author_retry_authorized=False,delivery_approval=False)
    c.execute('INSERT INTO verified_tool_incidents VALUES(?,?,?,?)',
        (issue,source,fingerprint,json.dumps(receipt,sort_keys=True)))
    return receipt


def capture(b,issue,source):
    try:import artifact_rejection_evidence
    except ImportError:from broker import artifact_rejection_evidence
    # Fetch from owned proxy/immutable private archive, never from agent text.
    diagnostic=artifact_rejection_evidence.fetch(b,issue,source)
    if not diagnostic or diagnostic.get('category')!='invalid_forced_argument':return None
    with b.db() as c:
        row=c.execute('SELECT stage,data FROM delivery_handoffs WHERE issue_id=? AND source_task=?',
            (issue,source)).fetchone()
        route=c.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(issue,)).fetchone()
        config=json.loads(route[0]) if route else {}
        latest=c.execute('SELECT source_task FROM delivery_handoffs WHERE issue_id=? ORDER BY updated DESC LIMIT 1',
            (issue,)).fetchone()
        snapshot=c.execute('SELECT status FROM failed_execution_snapshots WHERE task_id=?',(source,)).fetchone()
        binding=c.execute('SELECT n.request_id,l.status FROM native_bindings n JOIN leases l USING(request_id) '
            'WHERE n.task_id=? AND n.issue_id=?',(source,issue)).fetchall()
        if (not row or row['stage']!='test_first_blocked' or not latest or latest[0]!=source
                or json.loads(row['data']).get('error')!='test_first_correction_failed_after_cto_diagnosis'
                or json.loads(row['data']).get('diagnostic')!=diagnostic
                or config.get('enabled') is not True or config.get('test_first') is not True
                or not config.get('author') or config.get('author')==config.get('cto')
                or not snapshot or snapshot[0]!='complete' or len(binding)!=1
                or binding[0]['status'] not in ('failed','closed') or binding[0]['request_id']!=diagnostic['execution_id']
                or c.execute('SELECT 1 FROM test_first_red WHERE issue_id=?',(issue,)).fetchone()
                or c.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','active','closing')").fetchone()):
            return None
        return claim(c,issue,source,diagnostic)


def qualified(c,issue,source,data):
    receipt=data.get('verified_tool_incident')
    if not isinstance(receipt,dict) or not c.execute("SELECT 1 FROM sqlite_master WHERE name='verified_tool_incidents'").fetchone():return False
    row=c.execute('SELECT receipt FROM verified_tool_incidents WHERE issue_id=? AND source_task=?',(issue,source)).fetchone()
    return bool(row and json.loads(row[0])==receipt
        and receipt.get('diagnostic_sha256')==digest(data.get('diagnostic'))
        and receipt.get('author_retry_authorized') is False and receipt.get('delivery_approval') is False)


def measured_fact(diagnostic):
    """Plain-language interpretation of canonical values, not model prose."""
    from artifact_rejection_receipts import from_event
    if not isinstance(diagnostic,dict):return None
    shape=diagnostic.get('structure')
    if not shape:return None
    canonical=from_event(dict(event='model_proxy_request',status=502,
        artifact_contract_present=True,artifact_selected_tool=diagnostic.get('tool'),
        artifact_rejection_category=diagnostic.get('category'),execution_id=diagnostic.get('execution_id'),
        call_number=diagnostic.get('call_number'),artifact_rejection_diagnostic=shape))
    if not canonical or canonical.get('structure')!=shape:return None
    meanings={'no_change':'old_string equals new_string; the proposed patch changes no bytes.',
        'enum':'The supplied value is outside the pinned allowed values.',
        'type':'The supplied value has the wrong schema type.',
        'length':'The supplied value violates the pinned length bound.',
        'utf8_length':'The supplied value violates the UTF-8 byte bound.'}
    return dict(field=shape['field'],constraint=shape['constraint'],meaning=meanings[shape['constraint']],
        scope='this exact rejected response only',constraint_known=True,
        write_executed=False,tests_executed=False,delivery_approval=False)


def presentation_capture(b,issue,source):
    """One changed presentation after a terminal independent escalation."""
    with b.db() as c:
        row=c.execute('SELECT stage,data FROM delivery_handoffs WHERE issue_id=? AND source_task=?',(issue,source)).fetchone()
        if not row or row['stage']!='test_first_blocked':return None
        data=json.loads(row['data'])
        if (data.get('error')!='test_first_cto_requires_replanning'
                or data.get('decision',{}).get('action')!='escalate_cto'
                or not data.get('cto_task') or data.get('constraint_presentation_replay')
                or not qualified(c,issue,source,data)
                or data['verified_tool_incident'].get('cause_known') is not True
                or c.execute('SELECT 1 FROM test_first_red WHERE issue_id=?',(issue,)).fetchone()
                or c.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','active','closing')").fetchone()):return None
        fact=measured_fact(data.get('diagnostic'))
        if not fact:return None
        route=c.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(issue,)).fetchone()
        route=json.loads(route[0]) if route else {}
        latest=c.execute('SELECT source_task FROM delivery_handoffs WHERE issue_id=? ORDER BY updated DESC LIMIT 1',(issue,)).fetchone()
        snapshot=c.execute('SELECT status FROM failed_execution_snapshots WHERE task_id=?',(source,)).fetchone()
        if (route.get('enabled') is not True or route.get('test_first') is not True
                or not route.get('author') or route.get('author')==route.get('cto')
                or not latest or latest[0]!=source or not snapshot or snapshot[0]!='complete'):return None
        c.execute('CREATE TABLE IF NOT EXISTS constraint_presentations('
            'issue_id TEXT PRIMARY KEY,source_task TEXT,receipt TEXT)')
        proof=dict(operation='measured_constraint_presentation_v1',issue_id=issue,source_task=source,
            previous_cto_task=data['cto_task'],diagnostic_sha256=digest(data['diagnostic']),
            measured_fact=fact,author_retry_authorized=False,delivery_approval=False)
        old=c.execute('SELECT source_task,receipt FROM constraint_presentations WHERE issue_id=?',(issue,)).fetchone()
        if old:
            if old[0]!=source or json.loads(old[1])!=proof:return None
            return proof
        c.execute('INSERT INTO constraint_presentations VALUES(?,?,?)',(issue,source,json.dumps(proof,sort_keys=True)))
        return proof


def presentation_qualified(c,issue,source,data):
    proof=(data.get('constraint_presentation_replay') or {}).get('certificate')
    if not proof or not c.execute("SELECT 1 FROM sqlite_master WHERE name='constraint_presentations'").fetchone():return False
    row=c.execute('SELECT source_task,receipt FROM constraint_presentations WHERE issue_id=?',(issue,)).fetchone()
    return bool(row and row[0]==source and json.loads(row[1])==proof
        and proof.get('diagnostic_sha256')==digest(data.get('diagnostic'))
        and proof.get('measured_fact')==measured_fact(data.get('diagnostic'))
        and proof.get('author_retry_authorized') is False and proof.get('delivery_approval') is False)
