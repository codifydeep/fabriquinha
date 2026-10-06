"""Register a changed runtime once; CTO, not the operator, authorizes retry."""
import hashlib
import json
import re
import time
import urllib.request


def register(broker, payload):
    fields = {'source_task', 'failure_signature', 'worker_image'}
    if (not isinstance(payload, dict) or set(payload) != fields
            or not re.fullmatch(r'[a-f0-9-]{36}', payload.get('source_task', ''))
            or not re.fullmatch(r'[a-f0-9]{64}', payload.get('failure_signature', ''))
            or not re.fullmatch(r'sha256:[a-f0-9]{64}', payload.get('worker_image', ''))
            or payload['worker_image'] != broker.IMAGE):
        raise ValueError('exact installed runtime and failed source required')
    try:
        import handoffs, native, worker_model_config
    except ImportError:
        from broker import handoffs, native, worker_model_config
    if '  api_max_retries: 1\n' not in worker_model_config.EXPECTED:
        raise ValueError('single API attempt runtime required')
    with broker.LOCK, broker.db() as con:
        con.execute('CREATE TABLE IF NOT EXISTS execution_stall_repairs('
                    'issue_id TEXT, worker_image TEXT, receipt TEXT, '
                    'PRIMARY KEY(issue_id,worker_image))')
        row = con.execute('SELECT * FROM delivery_handoffs WHERE source_task=?',
                          (payload['source_task'],)).fetchone()
        if not row:
            raise ValueError('failed source missing')
        prior = con.execute('SELECT receipt FROM execution_stall_repairs '
                            'WHERE issue_id=? AND worker_image=?',
                            (row['issue_id'], broker.IMAGE)).fetchone()
        if prior:
            receipt = json.loads(prior[0])
            if receipt['request'] != payload:
                raise ValueError('runtime already tried for this issue; technical replan required')
            return receipt
        data = json.loads(row['data'])
        malformed = data.get('control_error', '').startswith('JSONDecodeError:')
        if not malformed:
            # Later dependency reads can replace the visible control_error.
            # Use the durable event for the SAME failed decision, never an
            # unrelated historical parse error or textual operator assertion.
            for event in con.execute('SELECT data FROM delivery_handoff_events WHERE source_task=?',
                                     (payload['source_task'],)):
                old = json.loads(event[0])
                if (old.get('recipient_task') == data.get('recipient_task')
                        and old.get('failure_signature') == data.get('failure_signature')
                        and old.get('control_error', '').startswith('JSONDecodeError:')):
                    malformed = True
        schema_repair = (malformed
                         and data.get('execution_repair_format_retry') is True
                         and not data.get('execution_repair_used')
                         and (data.get('execution_repair') or {}).get('request', {}).get('worker_image')
                             not in (None, broker.IMAGE))
        route = json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',
                                       (row['issue_id'],)).fetchone()[0])
        latest = con.execute('SELECT source_task FROM delivery_handoffs WHERE issue_id=? '
                             'ORDER BY updated DESC LIMIT 1', (row['issue_id'],)).fetchone()[0]
        if (row['stage'] != 'technical_decision_required' or latest != payload['source_task']
                or data.get('failure_signature') != payload['failure_signature']
                or data.get('error') != 'author_execution_failed'
                or data.get('source_failure_reason') != 'idle_watchdog'
                or data.get('validation_failure') or route['enabled']
                or data.get('target') != route['cto']
                or ((data.get('decision') or {}).get('action') != 'escalate_cto' and not schema_repair)
                or con.execute("SELECT 1 FROM leases WHERE status IN ('creating','running')").fetchone()):
            raise ValueError('current escalated idle stall and paused idle route required')
        settings = json.loads((broker.STATE / 'native.json').read_text())
        runs = native.issue_task_runs(settings, row['issue_id'])
        source = next((r for r in runs if r['id'] == payload['source_task']), None)
        decision = next((r for r in runs if r['id'] == data.get('recipient_task')), None)
        if (not source or source.get('status') != 'failed'
                or source.get('agent_id') != route['author']
                or not decision or decision.get('status') != 'completed'
                or decision.get('agent_id') != route['cto']
                or any(r.get('status') in ('queued', 'running') for r in runs)):
            raise ValueError('failed author, completed CTO and idle native tasks required')
        with urllib.request.urlopen('http://model-proxy:8080/runtime-status', timeout=5) as response:
            proxy = json.loads(response.read(2048))
        if proxy.get('response_deadline_seconds') != 120:
            raise ValueError('verified 120-second model response deadline required')
        if schema_repair and proxy.get('runtime_decision_contract') != 'no-tools-json-v1':
            raise ValueError('verified changed decision transport required')
        receipt = {'request': payload, 'issue_id': row['issue_id'],
                   'prior_decision_task': decision['id'], 'at': time.time(),
                   'config_sha256': hashlib.sha256(worker_model_config.EXPECTED.encode()).hexdigest(),
                   'api_max_retries': 1, 'response_deadline_seconds': 120,
                   'status': 'runtime_changed_not_delivery_approved',
                   'source_started_at': source.get('started_at'),
                   'source_completed_at': source.get('completed_at')}
        if schema_repair:
            receipt['decision_transport_repair'] = 'no-tools-json-v1'
        data['execution_repair'] = receipt
        data['diagnostic_revision'] = broker.IMAGE + ':single-api-attempt-v1'
        data['trigger_task'] = decision['id']
        for field in ('recipient_task', 'wakeup_id', 'dispatch_marker', 'dispatched_at',
                      'dispatch_stage', 'instruction', 'decision', 'control_error', 'control_error_count'):
            data.pop(field, None)
        con.execute('INSERT INTO execution_stall_repairs VALUES (?,?,?)',
                    (row['issue_id'], broker.IMAGE, json.dumps(receipt, sort_keys=True)))
        handoffs.save(con, payload['source_task'], row['issue_id'], 'diagnose_cto',
                      route['cto'], data, time.time())
        return receipt
