"""Once-only replay of a failed CTO diagnosis after a pinned contract repair.

This is an operator-qualified diagnostic replay, never an author retry or release
approval. Original incident and phase evidence remain durably preserved.
"""
import hashlib
import json
from pathlib import Path
import time
import uuid
try:
    import handoffs, native
except ImportError:
    from broker import handoffs, native

FIXED_SOURCE_SHA = 'e4fd3719fab26bc5a3cc2ac2732fe0617e50f8e9dfdc77cbe039056ab029d1e9'
PRE_REVIEW_INFRA_SOURCE_SHA = '67c222d0e0c4e1b205fc32eb0d04d8dd022ab5c60eb904b44eeade2cd82ff63b'
VALIDATION_PENDING_SOURCE_SHA = '3e8c3c5f0c422b3ae9c0a5b825288af60a0904ce6c4bf400db49ec68fd272c45'
LEGACY_SOURCE_SHA = 'd911f64499a5ae44fd0c1583d2f3de092376933353ea1cbc856339e3a23ec718'
FINALIZATION_SOURCE_SHA = '17bada109325765d5dfb10b53e370eabecadc3203dff3cd1a1c7997aaa984833'
DEPENDENCY_DIAGNOSTIC_SOURCE_SHA = '5745afe1e7ba31c866266fbdf22cc847f13628c7be89773a7cd74c90e0fd5d24'
SCOPED_INSPECTION_SOURCE_SHA = 'ded8dcc98130da2f123b48884c9d19ca0f6f24c517f8a82ea1e3f3b2084e871d'
REVIEW_PRECONDITIONS_SOURCE_SHA = 'd4e02169989649408f6f1b8ca5aa258142a62541f92b867e255d7697875f8900'
FORMAT_PROXY_IMAGE = 'sha256:f6ac67c6ce961f82c9c488a720e5485dd4e63d53c796eb4a9fdfdd8a3d876b1e'


def format_rejection(b, execution, *, expected_image=FORMAT_PROXY_IMAGE):
    """Read only sanitized validator receipts from the owned, pinned proxy."""
    if str(uuid.UUID(execution)) != execution:
        raise ValueError('canonical execution required')
    name = b.PREFIX + '-model-proxy-1'
    proxy = b.docker('GET', '/containers/' + name + '/json')
    labels = (proxy or {}).get('Config', {}).get('Labels', {})
    if (not proxy or proxy['Image'] != expected_image
            or not proxy.get('State', {}).get('Running')
            or labels.get('com.docker.compose.project') != b.PREFIX
            or labels.get('com.docker.compose.service') != 'model-proxy'):
        raise ValueError('owned pinned format-feedback proxy required')
    script = ('import sys,json,sqlite3,model_proxy;from pathlib import Path;'
              'p=Path(model_proxy.COUNTER_PATH).with_name("deterministic-reads.sqlite");'
              'c=sqlite3.connect(p.as_uri()+"?mode=ro",uri=True);'
              'rows=c.execute("SELECT receipt FROM typed_decision_rejections WHERE execution_id=?",'
              '(sys.argv[1],)).fetchall();print(json.dumps([json.loads(r[0]) for r in rows]))')
    execution_record = b.docker('POST', '/containers/' + proxy['Id'] + '/exec',
        dict(AttachStdout=True, AttachStderr=False, Tty=True,
             Env=['PYTHONPATH=/'], Cmd=['python', '-c', script, execution]))
    conn = b.DockerConnection('localhost', timeout=10)
    try:
        conn.request('POST', '/v1.45/exec/' + execution_record['Id'] + '/start',
                     json.dumps(dict(Detach=False, Tty=True)), {'Content-Type': 'application/json'})
        response = conn.getresponse(); raw = response.read(16385)
        if response.status != 200 or len(raw) > 16384:
            raise ValueError('bounded rejection receipt unavailable')
    finally:
        conn.close()
    outcome = b.docker('GET', '/exec/' + execution_record['Id'] + '/json')
    if outcome.get('Running') or outcome.get('ExitCode') != 0:
        raise ValueError('rejection receipt query failed')
    rows = json.loads(raw)
    if len(rows) != 1:
        raise ValueError('unique format rejection required')
    return rows[0]


def register_format(b, payload):
    """Separate, once-only format repair; never recycle the contract repair."""
    if not isinstance(payload, dict) or set(payload) != {'issue_id', 'source_task', 'failed_task'}:
        raise ValueError('exact format replay identity required')
    for value in payload.values():
        if str(uuid.UUID(value)) != value: raise ValueError('canonical identity required')
    issue, source, failed = (payload[k] for k in ('issue_id', 'source_task', 'failed_task'))
    if hashlib.sha256(Path(handoffs.__file__).read_bytes()).hexdigest() not in {REVIEW_PRECONDITIONS_SOURCE_SHA, SCOPED_INSPECTION_SOURCE_SHA, FIXED_SOURCE_SHA, LEGACY_SOURCE_SHA, VALIDATION_PENDING_SOURCE_SHA, PRE_REVIEW_INFRA_SOURCE_SHA, FINALIZATION_SOURCE_SHA, DEPENDENCY_DIAGNOSTIC_SOURCE_SHA}:
        raise ValueError('pinned diagnosis contract required')
    with b.LOCK:
        with b.db() as c:
            c.execute('CREATE TABLE IF NOT EXISTS execution_diagnosis_format_repairs(issue_id TEXT PRIMARY KEY,receipt TEXT)')
            previous = c.execute('SELECT receipt FROM execution_diagnosis_format_repairs WHERE issue_id=?', (issue,)).fetchone()
            if previous:
                receipt = json.loads(previous[0])
                if receipt['request'] != payload: raise ValueError('format replay already consumed')
                return receipt
            row = handoffs.load(c, source)
            route_row = c.execute('SELECT config FROM delivery_routes WHERE issue_id=?', (issue,)).fetchone()
            if not row or not route_row: raise ValueError('existing incident required')
            route, data = json.loads(route_row[0]), json.loads(row['data'])
            repair = data.get('execution_diagnosis_contract_repair') or {}
            latest = c.execute('SELECT source_task FROM delivery_handoffs WHERE issue_id=? ORDER BY updated DESC LIMIT 1', (issue,)).fetchone()
            if (row['issue_id'] != issue or row['stage'] != 'technical_decision_required'
                    or row['owner'] != route['cto'] or latest[0] != source or not route.get('enabled')
                    or route['author'] == route['cto'] or data.get('source_status') != 'failed'
                    or data.get('source_failure_reason') != 'agent_error.process_failure'
                    or data.get('error') != 'recipient_execution_failed' or data.get('recipient_task') != failed
                    or data.get('target') != route['cto'] or data.get('failed_dispatch_stage') != 'diagnose_cto'
                    or data.get('validation_failure') or data.get('execution_repair')
                    or data.get('execution_diagnosis_format_repair')
                    or 'DELIVERY_EXECUTION_DIAGNOSIS_V1' not in data.get('instruction', '')
                    or repair.get('installed_source_sha') not in {REVIEW_PRECONDITIONS_SOURCE_SHA, SCOPED_INSPECTION_SOURCE_SHA, FIXED_SOURCE_SHA, LEGACY_SOURCE_SHA, FINALIZATION_SOURCE_SHA, DEPENDENCY_DIAGNOSTIC_SOURCE_SHA}
                    or repair.get('request', {}).get('source_task') != source
                    or repair.get('request', {}).get('issue_id') != issue
                    or repair.get('author_retry_authorized') is not False
                    or repair.get('delivery_approval') is not False):
                raise ValueError('exact typed CTO format incident required')
            if c.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone():
                raise ValueError('idle format replay required')
            bindings = c.execute('SELECT request_id,agent_id,issue_id FROM native_bindings WHERE task_id=?', (failed,)).fetchall()
            if len(bindings) != 1 or bindings[0]['agent_id'] != route['cto'] or bindings[0]['issue_id'] != issue:
                raise ValueError('exact independent CTO execution binding required')
            execution = bindings[0]['request_id']
        runs = native.issue_task_runs(json.loads((b.STATE / 'native.json').read_text()), issue)
        author = next((r for r in runs if r['id'] == source), None)
        recipient = next((r for r in runs if r['id'] == failed), None)
        authors = [r for r in runs if r.get('agent_id') == route['author']]
        if (not author or author.get('status') != 'failed'
                or author.get('failure_reason') != 'agent_error.process_failure'
                or not authors or max(authors, key=lambda r: (r.get('created_at') or '', r['id']))['id'] != source
                or not recipient or recipient.get('status') != 'failed' or recipient.get('agent_id') != route['cto']
                or recipient.get('wakeup_id') != data.get('wakeup_id')
                or recipient.get('error') != 'hermes provider error: API call failed after 1 retries'
                or any(r.get('status') in ('queued','dispatched','running') for r in runs)):
            raise ValueError('matching native failures required')
        rejection = format_rejection(b, execution)
        if (rejection.get('operation') != 'rejected_typed_decision_adapter_v1'
                or rejection.get('category') != 'typed_schema_maxLength'
                or rejection.get('delivery_approval') is not False or rejection.get('worker_tool_executed') is not False
                or len(rejection.get('upstream_sha256', '')) != 64):
            raise ValueError('durable length-only rejection required')
        receipt = dict(request=payload, repair_kind='typed_execution_length_feedback_v1',
                       execution_id=execution, rejection=rejection, proxy_image=FORMAT_PROXY_IMAGE,
                       previous_handoff=dict(row), author_retry_authorized=False, delivery_approval=False, at=time.time())
        updated = dict(data, error='author_execution_failed', execution_diagnosis_format_repair=receipt,
                       diagnostic_revision=source + ':length-feedback-v1', trigger_task=failed)
        for field in ('recipient_task','wakeup_id','dispatch_marker','dispatch_stage','dispatched_at',
                      'target','instruction','decision','control_error','control_error_count','alerted'):
            updated.pop(field, None)
        with b.db() as c:
            if dict(handoffs.load(c, source)) != dict(row): raise ValueError('incident changed during qualification')
            if c.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone():
                raise ValueError('execution started during qualification')
            c.execute('INSERT INTO execution_diagnosis_format_repairs VALUES (?,?)', (issue, json.dumps(receipt, sort_keys=True)))
            handoffs.save(c, source, issue, 'diagnose_cto', route['cto'], updated, time.time())
        return receipt


def register(b, payload):
    if not isinstance(payload, dict) or set(payload) != {'issue_id', 'source_task', 'failed_task'}:
        raise ValueError('exact diagnostic replay identity required')
    for value in payload.values():
        if str(uuid.UUID(value)) != value:
            raise ValueError('canonical diagnostic replay identity required')
    issue, source, failed = (payload[k] for k in ('issue_id', 'source_task', 'failed_task'))
    source_sha = hashlib.sha256(Path(handoffs.__file__).read_bytes()).hexdigest()
    if source_sha not in {REVIEW_PRECONDITIONS_SOURCE_SHA, SCOPED_INSPECTION_SOURCE_SHA, FIXED_SOURCE_SHA, LEGACY_SOURCE_SHA, VALIDATION_PENDING_SOURCE_SHA, PRE_REVIEW_INFRA_SOURCE_SHA, FINALIZATION_SOURCE_SHA, DEPENDENCY_DIAGNOSTIC_SOURCE_SHA}:
        raise ValueError('pinned typed execution diagnosis repair required')
    with b.LOCK:
        with b.db() as c:
            c.execute('CREATE TABLE IF NOT EXISTS execution_diagnosis_repairs(issue_id TEXT PRIMARY KEY,receipt TEXT)')
            old = c.execute('SELECT receipt FROM execution_diagnosis_repairs WHERE issue_id=?', (issue,)).fetchone()
            if old:
                receipt = json.loads(old[0])
                if receipt['request'] != payload:
                    raise ValueError('diagnostic replay already consumed')
                return receipt
            row = handoffs.load(c, source)
            route_row = c.execute('SELECT config FROM delivery_routes WHERE issue_id=?', (issue,)).fetchone()
            if not row or not route_row:
                raise ValueError('existing diagnostic incident required')
            route, data = json.loads(route_row[0]), json.loads(row['data'])
            latest = c.execute('SELECT source_task FROM delivery_handoffs WHERE issue_id=? ORDER BY updated DESC LIMIT 1', (issue,)).fetchone()
            if (row['issue_id'] != issue or row['stage'] != 'technical_decision_required'
                    or row['owner'] != route['cto'] or latest[0] != source
                    or not route.get('enabled') or route['author'] == route['cto']
                    or data.get('source_status') != 'failed'
                    or data.get('source_failure_reason') != 'agent_error.process_failure'
                    or data.get('error') != 'recipient_execution_failed'
                    or data.get('recipient_task') != failed
                    or data.get('target') != route['cto']
                    or data.get('failed_dispatch_stage') != 'diagnose_cto'
                    or data.get('validation_failure') or data.get('execution_repair')
                    or data.get('execution_diagnosis_contract_repair')
                    or 'DELIVERY_EXECUTION_DIAGNOSIS_V1' in data.get('instruction', '')):
                raise ValueError('exact contract-loss CTO incident required')
            if c.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone():
                raise ValueError('idle diagnostic replay required')
        settings = json.loads((b.STATE / 'native.json').read_text())
        runs = native.issue_task_runs(settings, issue)
        author = next((r for r in runs if r['id'] == source), None)
        recipient = next((r for r in runs if r['id'] == failed), None)
        authors = [r for r in runs if r.get('agent_id') == route['author']]
        if (not author or author.get('status') != 'failed' or author.get('agent_id') != route['author']
                or author.get('failure_reason') != 'agent_error.process_failure'
                or max(authors, key=lambda r: (r.get('created_at') or '', r['id']))['id'] != source
                or not recipient or recipient.get('status') != 'failed'
                or recipient.get('agent_id') != route['cto']
                or recipient.get('wakeup_id') != data.get('wakeup_id')
                or recipient.get('error') != 'hermes provider error: API call failed after 1 retries'
                or any(r.get('status') in ('queued', 'dispatched', 'running') for r in runs)):
            raise ValueError('matching idle native failures required')
        receipt = dict(request=payload, repair_kind='preserve_typed_failed_author_scope_v1',
            installed_source_sha=source_sha, previous_handoff=dict(row),
            author_retry_authorized=False, delivery_approval=False, at=time.time())
        updated = dict(data, error='author_execution_failed',
            execution_diagnosis_contract_repair=receipt,
            diagnostic_revision=source + ':typed-execution-diagnosis-v1', trigger_task=failed)
        for field in ('recipient_task','wakeup_id','dispatch_marker','dispatch_stage','dispatched_at',
                      'target','instruction','decision','control_error','control_error_count','alerted'):
            updated.pop(field, None)
        with b.db() as c:
            if dict(handoffs.load(c, source)) != dict(row):
                raise ValueError('diagnostic incident changed during qualification')
            c.execute('INSERT INTO execution_diagnosis_repairs VALUES (?,?)', (issue, json.dumps(receipt, sort_keys=True)))
            handoffs.save(c, source, issue, 'diagnose_cto', route['cto'], updated, time.time())
        return receipt
