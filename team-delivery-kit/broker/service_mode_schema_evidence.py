"""One durable fixed harness experiment and independent CTO diagnosis.

No worker-facing endpoint, arbitrary command, third revision, or approval.
An interrupted capture is inspected by exact identity, never blindly restarted.
"""
import hashlib
import json
import os
import re
import time
try:
    import native, handoffs, docker_grouping, service_mode_harness_spike as probe
except ImportError:
    from broker import native, handoffs, service_mode_harness_spike as probe
    import docker_grouping


def validate_proof(proof, test_hash):
    if (not isinstance(proof, dict) or set(proof) != {
            'operation', 'input_sha256', 'report_sha256', 'snapshot_manifest_sha256',
            'facts', 'inputs_unchanged', 'delivery_approval', 'valid_red_green_receipt'}
            or proof['operation'] != 'service_mode_harness_schema_v1'
            or proof['inputs_unchanged'] is not True or proof['delivery_approval'] is not False
            or proof['valid_red_green_receipt'] is not False
            or set(proof['input_sha256']) != set(probe.READ_FILES)
            or proof['input_sha256'][probe.TEST] != test_hash
            or any(not isinstance(v, str) or not re.fullmatch('[a-f0-9]{64}', v)
                   for v in [*proof['input_sha256'].values(), proof['report_sha256'],
                             proof['snapshot_manifest_sha256']])):
        raise ValueError('exact nonapproving immutable schema proof required')
    facts = proof['facts']
    if not isinstance(facts, dict) or set(facts) != {'after_ok', 'pending_observed', 'after_deferred'}:
        raise ValueError('bounded fixed harness facts required')
    for fact in facts.values():
        required = {'value_type', 'has_calls', 'has_issued', 'text_type', 'is_checking', 'is_demo'}
        if (not isinstance(fact, dict) or set(fact) not in (required, required | {'calls'})
                or fact['value_type'] not in ('dict', 'str', 'NoneType')
                or fact['text_type'] not in ('dict', 'str', 'NoneType', None)
                or any(type(fact[k]) is not bool for k in ('has_calls', 'has_issued', 'is_checking', 'is_demo'))
                or ('calls' in fact and (type(fact['calls']) is not int or not 0 <= fact['calls'] <= 64))):
            raise ValueError('unsafe or unbounded harness fact')
    return proof


def capture(b, source, volume, test_hash, image, *, resume=False):
    name = b.PREFIX + '-service-mode-schema-' + source
    # broker.docker applies grouped_create's canonical disposable-job labels.
    labels = {**docker_grouping.labels(namespace=b.PREFIX),
              'delivery-kit.owner': b.OWNER, 'delivery-kit.source-task': source}
    existing = b.docker('GET', '/containers/' + name + '/json')
    if existing:
        host = existing.get('HostConfig') or {}
        mounts = existing.get('Mounts') or []
        if (not resume or any(existing['Config'].get('Labels', {}).get(k) != v for k, v in labels.items())
                or existing['Image'] != image
                or existing['Config'].get('Cmd') != ['/service_mode_harness_spike.py', test_hash]
                or existing['Config'].get('Entrypoint') != ['python']
                or existing['Config'].get('User') != '10000:10000'
                or host.get('NetworkMode') != 'none' or host.get('ReadonlyRootfs') is not True
                or host.get('Privileged') or host.get('CapDrop') != ['ALL']
                or host.get('Devices') or host.get('Binds')
                or len(mounts) != 1 or mounts[0].get('Type') != 'volume'
                or mounts[0].get('Name') != volume or mounts[0].get('Destination') != '/delivery'
                or mounts[0].get('RW') is not False):
            raise ValueError('exact interrupted schema probe required')
        if not existing['State'].get('StartedAt') or existing['State']['StartedAt'].startswith('0001-'):
            raise ValueError('unstarted probe retained; no automatic repeat')
    elif resume:
        raise ValueError('interrupted probe handle missing; no automatic repeat')
    else:
        b.docker('POST', '/containers/create?name=' + name, {
            'Image': image, 'User': '10000:10000', 'Entrypoint': ['python'],
            'Cmd': ['/service_mode_harness_spike.py', test_hash], 'NetworkDisabled': True,
            'Labels': labels,
            'HostConfig': {'ReadonlyRootfs': True, 'NetworkMode': 'none', 'CapDrop': ['ALL'],
                           'SecurityOpt': ['no-new-privileges'], 'Memory': 268435456, 'PidsLimit': 64,
                           'Mounts': [{'Type': 'volume', 'Source': volume, 'Target': '/delivery', 'ReadOnly': True}]}})
        b.docker('POST', '/containers/' + name + '/start')
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        info = b.docker('GET', '/containers/' + name + '/json')
        if not info:
            raise ValueError('probe disappeared; no automatic repeat')
        if not info['State']['Running']:
            if info['State']['ExitCode']:
                raise ValueError('fixed schema probe rejected evidence; retain stopped job')
            # Retain stopped owned job for inspection. Archive the proof before
            # any later exact-ID cleanup; never force-delete in a finally block.
            return validate_proof(json.loads(b.docker_stdout(name, limit=8192)), test_hash)
        time.sleep(.2)
    raise TimeoutError('probe observation deadline; retain handle')


def register(b, payload):
    if (not isinstance(payload, dict) or set(payload) != {'source_task', 'decision_task', 'output_sha256'}
            or any(not isinstance(payload[k], str) or not re.fullmatch('[a-f0-9-]{36}', payload[k])
                   for k in ('source_task', 'decision_task'))
            or not isinstance(payload['output_sha256'], str)
            or not re.fullmatch('[a-f0-9]{64}', payload['output_sha256'])):
        raise ValueError('exact source, CTO decision and failure hash required')
    source = payload['source_task']
    with b.LOCK:
        with b.db() as con:
            con.execute('CREATE TABLE IF NOT EXISTS service_mode_schema_experiments('
                        'source_task TEXT PRIMARY KEY,request TEXT,state TEXT)')
            old = con.execute('SELECT request,state FROM service_mode_schema_experiments WHERE source_task=?', (source,)).fetchone()
            state = json.loads(old['state']) if old else None
            if old and json.loads(old['request']) != payload:
                raise ValueError('schema experiment identity drift')
            if state and state['stage'] == 'complete':
                return state['receipt']
            row = handoffs.load(con, source)
            if not row or row['stage'] not in ('test_revision_required', 'technical_decision_required'):
                raise ValueError('blocked independent CTO diagnosis required')
            data = json.loads(row['data'])
            route = json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?', (row['issue_id'],)).fetchone()[0])
            failure = data.get('validation_failure') or {}
            diagnostic = data.get('failed_execution_diagnostic') or {}
            saved_diagnostic = con.execute('SELECT receipt FROM failed_execution_diagnoses WHERE source_task=?', (source,)).fetchone()
            saved = con.execute('SELECT output FROM frozen_suite_failures WHERE task_id=? AND output_sha256=?',
                                (source, payload['output_sha256'])).fetchone()
            snapshot = con.execute("SELECT volume FROM failed_execution_snapshots WHERE task_id=? AND status='complete'", (source,)).fetchone()
            latest = con.execute('SELECT source_task FROM delivery_handoffs WHERE issue_id=? ORDER BY updated DESC LIMIT 1', (row['issue_id'],)).fetchone()[0]
            if (latest != source or route['enabled'] or route['author'] == route['cto']
                    or con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone()
                    or data.get('recipient_task') != payload['decision_task'] or data.get('target') != route['cto']
                    or (data.get('decision') or {}).get('action') not in ('request_test_revision', 'escalate_cto')
                    or not saved_diagnostic or json.loads(saved_diagnostic[0]) != diagnostic
                    or failure != diagnostic.get('failure') or failure.get('phase') != 'failed_execution_diagnostic'
                    or failure.get('category') != 'executed_test_failure'
                    or failure.get('output_sha256') != payload['output_sha256']
                    or not snapshot or snapshot[0] != diagnostic.get('volume')
                    or not saved or hashlib.sha256(saved[0].encode()).hexdigest() != payload['output_sha256']
                    or set(route['test_first_files']) != {probe.TEST}
                    or set(failure.get('diagnostic_read_files', [])) | {probe.TEST} != set(probe.READ_FILES)):
                raise ValueError('current paused idle immutable failed source required')
            red = json.loads(con.execute('SELECT receipt FROM test_first_red WHERE issue_id=?', (row['issue_id'],)).fetchone()[0])
            test_hash = red['red']['test_sha256'][probe.TEST]
        settings = json.loads((b.STATE / 'native.json').read_text())
        runs = native.issue_task_runs(settings, row['issue_id'])
        task = next((r for r in runs if r['id'] == payload['decision_task']), {})
        author = next((r for r in runs if r['id'] == source), {})
        if (task.get('status') != 'completed' or task.get('agent_id') != route['cto']
                or task.get('issue_id') != row['issue_id'] or task.get('wakeup_id') != data.get('wakeup_id')
                or author.get('status') != 'failed' or author.get('agent_id') != route['author']
                or author.get('issue_id') != row['issue_id']
                or max((r for r in runs if r.get('agent_id') == route['author']),
                       key=lambda r: (r.get('created_at') or '', r['id']))['id'] != source
                or any(r['status'] in ('queued', 'running') for r in runs)):
            raise ValueError('authentic completed CTO and failed author required')
        volume = b.docker('GET', '/volumes/' + snapshot[0])
        labels = volume.get('Labels', {}) if volume else {}
        if (labels.get('delivery-kit.owner') != b.OWNER or labels.get('delivery-kit.source-task') != source
                or labels.get('delivery-kit.diagnostic-only') != 'true'):
            raise ValueError('fixed diagnostic snapshot identity required')
        image = b.docker('GET', '/containers/' + os.environ['HOSTNAME'] + '/json')['Image']
        if not re.fullmatch('sha256:[a-f0-9]{64}', image):
            raise ValueError('immutable helper image required')
        if state and (state['row'] != row or state['image'] != image):
            raise ValueError('interrupted experiment source changed')
        if not state:
            state = {'stage': 'capturing', 'row': row, 'image': image}
            with b.db() as con:
                con.execute('INSERT INTO service_mode_schema_experiments VALUES(?,?,?)',
                            (source, json.dumps(payload, sort_keys=True), json.dumps(state, sort_keys=True)))
        proof = capture(b, source, snapshot[0], test_hash, image, resume=bool(old))
        validate_proof(proof, test_hash)
        findings = [
            'Fixed isolated harness execution: after_ok=' + json.dumps(proof['facts']['after_ok'], separators=(',', ':')),
            'Fixed isolated harness execution: pending_observed=' + json.dumps(proof['facts']['pending_observed'], separators=(',', ':')),
            'Fixed isolated harness execution: after_deferred=' + json.dumps(proof['facts']['after_deferred'], separators=(',', ':')),
            'Inspect whether after_ok is captured before await flush and loadCallsSince counts ALL startup fetches rather than only /service-mode. Runtime facts are not a verdict.',
            'Two recursive test revisions are already used. Diagnose and replan without resetting depth, removing assertions, or claiming Green. Preserve exact demo matching, loading state, one service-mode fetch per load, no polling, accessibility and all board regressions.']
        diagnostic_proof = dict(approval=False, source_task=source, output_sha256=payload['output_sha256'],
                                file_sha256=proof['input_sha256'], findings=findings)
        receipt = dict(request=payload, issue_id=row['issue_id'], volume=snapshot[0], image=image,
                       red_manifest=red['red']['manifest_sha256'], proof=proof,
                       prior_decision=data['decision'], prior_decision_task=payload['decision_task'],
                       status='evidence_only_not_approved')
        with b.db() as con:
            current = handoffs.load(con, source)
            current_route = json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?', (row['issue_id'],)).fetchone()[0])
            if (current != row or current_route != route
                    or con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone()):
                raise ValueError('handoff changed during fixed experiment')
            data.update(harness_diagnosis=diagnostic_proof, service_mode_schema_evidence=receipt,
                        trigger_task=payload['decision_task'],
                        diagnostic_revision=proof['report_sha256'] + ':service-mode-schema-v1')
            # Do not reuse the old proposal or silently grant a new depth.
            for field in ('recipient_task', 'wakeup_id', 'dispatched_at', 'dispatch_marker', 'dispatch_stage',
                          'target', 'instruction', 'decision', 'control_error', 'control_error_count',
                          'test_revision_proposal', 'technical_replan_certificate'):
                data.pop(field, None)
            handoffs.harness_diagnosis_instruction(data, route)  # includes native note envelope margin
            con.execute('UPDATE service_mode_schema_experiments SET state=? WHERE source_task=?',
                        (json.dumps(dict(stage='complete', receipt=receipt), sort_keys=True), source))
            handoffs.save(con, source, row['issue_id'], 'diagnose_cto', route['cto'], data, time.time())
        return receipt
