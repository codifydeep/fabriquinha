"""Freeze failed work for diagnosis, never for delivery acceptance."""
import json
import re
import time


def register(broker, payload):
    if (not isinstance(payload, dict) or set(payload) != {'source_task', 'failure_signature'}
            or not isinstance(payload['source_task'], str)
            or not re.fullmatch(r'[a-f0-9-]{36}', payload['source_task'])
            or not isinstance(payload['failure_signature'], str)
            or not re.fullmatch(r'[a-f0-9]{64}', payload['failure_signature'])):
        raise ValueError('exact failed execution identity required')
    try:
        import native, handoffs
    except ImportError:
        from broker import native, handoffs
    source = payload['source_task']
    with broker.LOCK, broker.db() as con:
        con.execute('CREATE TABLE IF NOT EXISTS failed_execution_diagnoses('
                    'source_task TEXT PRIMARY KEY,receipt TEXT)')
        prior = con.execute('SELECT receipt FROM failed_execution_diagnoses WHERE source_task=?',
                            (source,)).fetchone()
        if prior:
            receipt = json.loads(prior[0])
            if receipt['request'] != payload:
                raise ValueError('failed diagnostic identity drift')
            return receipt
        row = con.execute('SELECT * FROM delivery_handoffs WHERE source_task=?', (source,)).fetchone()
        if not row or row['stage'] != 'technical_decision_required':
            raise ValueError('blocked failed execution required')
        data = json.loads(row['data'])
        if (data.get('failure_signature') != payload['failure_signature']
                or data.get('error') != 'author_execution_failed'):
            raise ValueError('failed execution evidence mismatch')
        latest = con.execute('SELECT source_task FROM delivery_handoffs WHERE issue_id=? '
                             'ORDER BY updated DESC LIMIT 1', (row['issue_id'],)).fetchone()
        route = json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',
                                       (row['issue_id'],)).fetchone()[0])
        if (latest[0] != source or route['enabled']
                or con.execute("SELECT 1 FROM leases WHERE status IN ('creating','running')").fetchone()):
            raise ValueError('current failed source and paused idle route required')
        settings = json.loads((broker.STATE / 'native.json').read_text())
        runs = native.issue_task_runs(settings, row['issue_id'])
        original = next((r for r in runs if r['id'] == source), None)
        authors = [r for r in runs if r.get('agent_id') == route['author']]
        if (not original or original.get('status') != 'failed'
                or original.get('agent_id') != route['author']
                or max(authors, key=lambda r: (r.get('created_at') or '', r['id']))['id'] != source
                or any(r.get('status') in ('queued', 'running') for r in runs)):
            raise ValueError('latest failed author and idle native tasks required')
        # Release the read transaction before snapshot creation commits independently.
    snapshot = broker.snapshot_submission({'task_id': source}, diagnostic=True)
    volume = snapshot['volume']
    effects = broker.handoff_runtime.Effects(broker, settings)
    red = effects.test_first_red(source)
    if not red:
        raise ValueError('immutable Red required for failed execution diagnosis')
    broker.verify_test_first_green(volume, source, red)  # hashes only; not Green
    try:
        broker.validate_frozen_delivery(volume, source)
    except Exception as error:
        failure = getattr(error, 'validation_failure', None)
        if not isinstance(failure, dict) or failure.get('category') != 'executed_test_failure':
            raise ValueError('executed functional failure required; infrastructure diagnosis remains blocked') from error
    else:
        raise ValueError('no functional failure; runtime diagnosis remains blocked')
    failure = {**failure, 'phase': 'failed_execution_diagnostic', 'diagnostic_only': True}
    with broker.LOCK, broker.db() as con:
        current = con.execute('SELECT * FROM delivery_handoffs WHERE source_task=?', (source,)).fetchone()
        current_data = json.loads(current['data'])
        current_route = json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',
                                               (row['issue_id'],)).fetchone()[0])
        if (current['data'] != row['data'] or current['stage'] != row['stage']
                or current_route != route
                or con.execute("SELECT 1 FROM leases WHERE status IN ('creating','running')").fetchone()):
            raise ValueError('handoff changed during diagnostic capture')
        receipt = {'request': payload, 'issue_id': row['issue_id'], 'volume': volume,
                   'failure': failure, 'status': 'diagnostic_only_not_approved'}
        current_data.update(validation_failure=failure, artifact_diagnosis=True,
                            failed_execution_diagnostic=receipt,
                            error='portable frozen suite failed',
                            diagnostic_revision=failure['output_sha256'] + ':failed-execution-v1')
        for field in ('wakeup_id', 'recipient_task', 'dispatched_at', 'dispatch_marker',
                      'dispatch_stage', 'target', 'trigger_task', 'instruction', 'decision',
                      'control_error', 'control_error_count', 'alerted'):
            current_data.pop(field, None)
        con.execute('INSERT INTO failed_execution_diagnoses VALUES (?,?)',
                    (source, json.dumps(receipt, sort_keys=True)))
        handoffs.save(con, source, row['issue_id'], 'diagnose_cto', route['cto'], current_data, time.time())
        return receipt
