"""Once-only inspection-precondition repair; no author retry or approval."""
import copy
import json
import time
import uuid

VALIDATOR = 'sha256:e9657d5e999de4b522217cbd30cc6a153c7dad8ce38be602d6b70d141720d186'


def prepare(row, failure):
    data = json.loads(row['data'])
    previous = data.get('validation_failure') or {}
    if (row['stage'] != 'technical_decision_required' or data.get('diagnostic_inventory_recovery')
            or previous.get('category') != 'executed_test_failure'
            or failure.get('category') != previous['category']
            or any(failure.get(k) != previous.get(k) for k in
                ('source_task', 'volume', 'output_sha256', 'tests_executed', 'failures'))
            or failure.get('source_task') != row['source_task']
            or not failure.get('missing_module_attributes')
            or not failure.get('diagnostic_source_hashes')
            or not set(previous.get('diagnostic_read_files', [])) < set(failure.get('diagnostic_read_files', []))):
        raise ValueError('same failed immutable delivery and new verified read context required')
    data['diagnostic_inventory_recovery'] = dict(previous_diagnosis=copy.deepcopy(data),
        validator_image=VALIDATOR, model_calls=0, author_restarted=False, delivery_approval=False)
    data['validation_failure'] = failure
    data['diagnostic_revision'] = failure['output_sha256'] + ':verified-dependency-inventory-v1'
    data['artifact_diagnosis'] = True
    for key in ('recipient_task', 'wakeup_id', 'dispatch_marker', 'dispatch_stage',
                'dispatched_at', 'target', 'instruction', 'decision', 'required_action'):
        data.pop(key, None)
    return data


def reconcile(b, source):
    if str(uuid.UUID(source)) != source or b.OFFLINE_IMAGE != VALIDATOR:
        raise ValueError('exact source and qualified validator required')
    import controller_maintenance, handoffs
    from suite_failure import FrozenSuiteFailure
    with b.LOCK, b.db() as con:
        if (controller_maintenance.current(con) or {}).get('stage') != 'sealed':
            raise ValueError('sealed maintenance required')
        row = handoffs.load(con, source)
        if not row: raise ValueError('existing source required')
        latest = con.execute('SELECT source_task FROM delivery_handoffs WHERE issue_id=? '
            'AND stage<>? ORDER BY updated DESC LIMIT 1', (row['issue_id'], 'superseded')).fetchone()
        snapshot = con.execute("SELECT volume FROM snapshots WHERE task_id=? AND status='complete'", (source,)).fetchone()
        if not latest or latest[0] != source or not snapshot: raise ValueError('current complete snapshot required')
        route = json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?', (row['issue_id'],)).fetchone()[0])
    try:
        b.validate_frozen_delivery(snapshot[0], source)
    except FrozenSuiteFailure as error:
        failure = error.validation_failure
    else:
        raise ValueError('this repair cannot approve a delivery or reinterpret Green')
    data = prepare(row, failure)
    with b.LOCK, b.db() as con:
        if handoffs.load(con, source) != row: raise ValueError('handoff changed during observation')
        handoffs.save(con, source, row['issue_id'], 'diagnose_cto', route['cto'], data, time.time())
    return dict(stage='diagnose_cto', additional_read_files=failure['diagnostic_read_files'],
                model_calls=0, author_restarted=False, delivery_approval=False)
