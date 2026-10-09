"""One fixed re-diagnosis after installing structured suite evidence."""
import json
import re
import time


def challenge(broker, payload):
    """One operator-observed contradiction; CTO must independently reread artifacts.

    This is not a decision override, test revision permission or Green receipt.
    Identity-bound once per failed source, including across restarts.
    """
    fields = {'source_task', 'failure_signature', 'decision_task', 'output_sha256', 'observation'}
    if (not isinstance(payload, dict) or set(payload) != fields
            or not isinstance(payload['source_task'], str)
            or not re.fullmatch(r'[a-f0-9-]{36}', payload['source_task'])
            or any(not isinstance(payload[k], str) or not re.fullmatch(r'[a-f0-9]{64}', payload[k])
                   for k in ('failure_signature', 'output_sha256'))
            or not isinstance(payload['decision_task'], str) or not payload['decision_task']
            or not isinstance(payload['observation'], str)
            or not 1 <= len(payload['observation']) <= 180):
        raise ValueError('bounded exact diagnostic challenge required')
    source = payload['source_task']
    with broker.LOCK, broker.db() as con:
        con.execute('CREATE TABLE IF NOT EXISTS suite_diagnostic_challenges('
                    'source_task TEXT PRIMARY KEY, receipt TEXT)')
        prior = con.execute('SELECT receipt FROM suite_diagnostic_challenges WHERE source_task=?',
                            (source,)).fetchone()
        if prior:
            receipt = json.loads(prior[0])
            if receipt['request'] != payload:
                raise ValueError('source already challenged; new technical replan required')
            return receipt
        row = con.execute('SELECT * FROM delivery_handoffs WHERE source_task=?', (source,)).fetchone()
        if not row or row['stage'] != 'test_revision_required':
            raise ValueError('recorded CTO test-revision decision required')
        data = json.loads(row['data'])
        if (data.get('failure_signature') != payload['failure_signature']
                or (data.get('validation_failure') or {}).get('output_sha256') != payload['output_sha256']
                or data.get('recipient_task') != payload['decision_task']
                or (data.get('decision') or {}).get('action') != 'request_test_revision'):
            raise ValueError('diagnostic challenge identity drift')
        latest = con.execute('SELECT source_task FROM delivery_handoffs WHERE issue_id=? '
                             'ORDER BY updated DESC LIMIT 1', (row['issue_id'],)).fetchone()
        route = json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',
                                       (row['issue_id'],)).fetchone()[0])
        snapshot = con.execute('SELECT status FROM snapshots WHERE task_id=?', (source,)).fetchone()
        failed_only = False
        if snapshot is None and data.get('failed_execution_diagnostic'):
            # A failed-work snapshot is never promoted into a normal delivery.
            # Require the exact controller-created executed diagnostic receipt,
            # including its volume and immutable test result, before a reread.
            failed_snapshot = con.execute('SELECT volume,status FROM failed_execution_snapshots WHERE task_id=?',(source,)).fetchone()
            stored = con.execute('SELECT receipt FROM failed_execution_diagnoses WHERE source_task=?',(source,)).fetchone()
            proof = json.loads(stored[0]) if stored else {}
            failure = proof.get('failure',{})
            failed_only = bool(failed_snapshot and failed_snapshot['status']=='complete'
                and proof==data['failed_execution_diagnostic']
                and proof.get('status')=='diagnostic_only_not_approved'
                and proof.get('volume')==failed_snapshot['volume']
                and proof.get('request')=={'source_task':source,'failure_signature':payload['failure_signature']}
                and failure==data.get('validation_failure')
                and failure.get('volume')==failed_snapshot['volume']
                and failure.get('source_task')==source
                and failure.get('category')=='executed_test_failure'
                and failure.get('diagnostic_only') is True
                and failure.get('phase')=='failed_execution_diagnostic'
                and data.get('source_status')=='failed'
                and not data.get('evidence') and not data.get('review'))
        if (latest[0] != source or not ((snapshot and snapshot['status']=='complete') or failed_only)
                or route['enabled'] or data.get('target') != route['cto']
                or con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone()):
            raise ValueError('challenge requires current immutable source and paused idle route')
        try:
            import native, handoffs
        except ImportError:
            from broker import native, handoffs
        settings = json.loads((broker.STATE / 'native.json').read_text())
        runs = native.issue_task_runs(settings, row['issue_id'])
        decision = next((r for r in runs if r['id'] == payload['decision_task']), None)
        if failed_only:
            authors=[r for r in runs if r.get('agent_id')==route['author']]
            if (not authors or max(authors,key=lambda r:(r.get('created_at') or '',r['id']))['id']!=source
                    or next(r for r in authors if r['id']==source).get('status')!='failed'):
                raise ValueError('latest failed author required for diagnostic-only challenge')
        if (not decision or decision.get('status') != 'completed'
                or decision.get('agent_id') != route['cto']
                or any(r.get('status') in ('queued', 'dispatched', 'running') for r in runs)):
            raise ValueError('completed CTO decision and idle native tasks required')
        receipt = {'request': payload, 'prior_decision': data['decision'],
                   'issue_id': row['issue_id'], 'at': time.time(),
                   'stage': 'contradiction_registered_not_approved'}
        data['diagnostic_challenge'] = {'observation': payload['observation'],
                                       'decision_task': payload['decision_task']}
        data['diagnostic_revision'] = payload['output_sha256'] + ':contradiction-v1'
        data['artifact_diagnosis'] = True
        data['trigger_task'] = payload['decision_task']
        for field in ('wakeup_id', 'recipient_task', 'dispatched_at', 'dispatch_marker',
                      'dispatch_stage', 'target', 'instruction', 'decision', 'alerted',
                      'test_revision_proposal', 'required_action', 'control_error', 'control_error_count'):
            data.pop(field, None)
        con.execute('INSERT INTO suite_diagnostic_challenges VALUES (?,?)',
                    (source, json.dumps(receipt, sort_keys=True)))
        handoffs.save(con, source, row['issue_id'], 'diagnose_cto', route['cto'], data, time.time())
        return receipt


def reopen(broker, payload):
    if not isinstance(payload, dict) or set(payload) not in (
            {'source_task', 'failure_signature'}, {'source_task', 'failure_signature', 'mode'}):
        raise ValueError('exact failed handoff identity required')
    artifact_mode = payload.get('mode') == 'artifact_cto'
    if 'mode' in payload and not artifact_mode:
        raise ValueError('invalid diagnostic mode')
    source = payload['source_task']
    if not isinstance(source, str) or not re.fullmatch(r'[a-f0-9-]{36}', source):
        raise ValueError('invalid source identity')
    with broker.LOCK, broker.db() as con:
        con.execute('CREATE TABLE IF NOT EXISTS suite_diagnostic_repairs('
                    'source_task TEXT PRIMARY KEY, receipt TEXT)')
        prior = con.execute('SELECT receipt FROM suite_diagnostic_repairs WHERE source_task=?',
                            (source,)).fetchone()
        if prior:
            receipt = json.loads(prior[0])
            if receipt['failure_signature'] != payload['failure_signature']:
                raise ValueError('diagnostic repair identity drift')
            row = con.execute('SELECT * FROM delivery_handoffs WHERE source_task=?', (source,)).fetchone()
            data = json.loads(row['data'])
            if (artifact_mode and not receipt.get('context_repaired')
                    and row['stage'] == 'technical_decision_required'
                    and data.get('artifact_diagnosis')
                    and data.get('failed_dispatch_stage') == 'diagnose_cto'
                    and data.get('recipient_error') == 'hermes session/prompt failed: session/prompt: restricted broker stream failed: broker_internal (code=-32000)'):
                route = json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',
                                                (row['issue_id'],)).fetchone()[0])
                if route['enabled'] or con.execute("SELECT 1 FROM leases WHERE status IN ('creating','running')").fetchone():
                    raise ValueError('context repair requires paused idle route')
                try:
                    import native, handoffs
                except ImportError:
                    from broker import native, handoffs
                settings = json.loads((broker.STATE / 'native.json').read_text())
                runs = native.issue_task_runs(settings, row['issue_id'])
                recipient = next((r for r in runs if r['id'] == data.get('recipient_task')), None)
                if not recipient or recipient.get('status') != 'failed' or any(
                        r.get('status') in ('queued', 'running') for r in runs):
                    raise ValueError('failed recipient and idle native tasks required')
                receipt.update(context_repaired=True, failed_recipient=data['recipient_task'])
                data['trigger_task'] = data['recipient_task']
                data['diagnostic_revision'] += ':context-v1'
                data['error'] = 'portable frozen suite failed'
                for field in ('recipient_task', 'wakeup_id', 'dispatched_at', 'dispatch_marker',
                              'instruction', 'recipient_error', 'failed_dispatch_stage'):
                    data.pop(field, None)
                con.execute('UPDATE suite_diagnostic_repairs SET receipt=? WHERE source_task=?',
                            (json.dumps(receipt, sort_keys=True), source))
                handoffs.save(con, source, row['issue_id'], 'diagnose_cto', route['cto'], data, time.time())
            if (artifact_mode and not receipt.get('transport_repaired')
                    and row['stage'] == 'technical_decision_required'
                    and data.get('artifact_diagnosis')
                    and data.get('control_error') == 'ValueError:handoff instruction too large'
                    and not data.get('wakeup_id') and not data.get('recipient_task')):
                route = json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',
                                                (row['issue_id'],)).fetchone()[0])
                if route['enabled'] or con.execute("SELECT 1 FROM leases WHERE status IN ('creating','running')").fetchone():
                    raise ValueError('transport repair requires paused idle route')
                for field in ('control_error', 'control_error_count', 'instruction'):
                    data.pop(field, None)
                receipt['transport_repaired'] = True
                con.execute('UPDATE suite_diagnostic_repairs SET receipt=? WHERE source_task=?',
                            (json.dumps(receipt, sort_keys=True), source))
                try:
                    import handoffs
                except ImportError:
                    from broker import handoffs
                handoffs.save(con, source, row['issue_id'], 'diagnose_cto', route['cto'], data, time.time())
            return receipt
        row = con.execute('SELECT * FROM delivery_handoffs WHERE source_task=?', (source,)).fetchone()
        allowed = ('technical_decision_required', 'awaiting_acceptance', 'accepted') if artifact_mode else ('technical_decision_required',)
        if not row or row['stage'] not in allowed:
            raise ValueError('exact blocked diagnostic handoff required')
        data = json.loads(row['data'])
        if (data.get('failure_signature') != payload['failure_signature']
                or data.get('error') != 'portable frozen suite failed'):
            raise ValueError('not the recorded frozen suite incident')
        latest = con.execute('SELECT source_task FROM delivery_handoffs WHERE issue_id=? '
                             'ORDER BY updated DESC LIMIT 1', (row['issue_id'],)).fetchone()
        if latest[0] != source:
            raise ValueError('stale diagnostic source')
        if con.execute("SELECT 1 FROM leases WHERE status IN ('creating','running')").fetchone():
            raise ValueError('workers must be idle for diagnostic repair')
        snapshot = con.execute('SELECT volume,status FROM snapshots WHERE task_id=?',
                               (source,)).fetchone()
        if not snapshot or snapshot['status'] != 'complete':
            raise ValueError('immutable source snapshot missing')
        route = json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',
                                        (row['issue_id'],)).fetchone()[0])
        if not route['enabled'] and not artifact_mode:
            raise ValueError('route is paused')
        if artifact_mode:
            if route['enabled']:
                raise ValueError('artifact diagnosis maintenance requires paused route')
            try:
                import native
            except ImportError:
                from broker import native
            settings = json.loads((broker.STATE / 'native.json').read_text())
            runs = native.issue_task_runs(settings, row['issue_id'])
            original = next((run for run in runs if run['id'] == source), None)
            if (not original or original.get('status') != 'completed'
                    or original.get('agent_id') != route['author']
                    or any(run.get('status') in ('queued', 'running') for run in runs)):
                raise ValueError('exact native source and all idle tasks required')
        try:
            broker.validate_frozen_delivery(snapshot['volume'], source)
        except Exception as error:
            failure = getattr(error, 'validation_failure', None)
            if not isinstance(failure, dict) or failure.get('category') != 'executed_test_failure':
                raise ValueError('no executed functional failure evidence') from error
        else:
            raise ValueError('suite now passes; no functional diagnosis repair needed')
        data['validation_failure'] = failure
        data['diagnostic_revision'] = failure['output_sha256'] + (':artifact-cto-v1' if artifact_mode else '')
        if artifact_mode:
            data['artifact_diagnosis'] = True
        for field in ('wakeup_id', 'recipient_task', 'dispatched_at', 'dispatch_marker',
                      'dispatch_stage', 'target', 'trigger_task', 'instruction',
                      'control_error', 'control_error_count', 'decision', 'alerted'):
            data.pop(field, None)
        receipt = {'source_task': source, 'issue_id': row['issue_id'],
                   'failure_signature': payload['failure_signature'],
                   'output_sha256': failure['output_sha256'],
                   'stage': 'structured_diagnosis_registered_not_approved'}
        # Receipt and intent commit together. A restart cannot dispatch a second
        # repair or erase the earlier handoff events / immutable Red.
        try:
            import handoffs
        except ImportError:
            from broker import handoffs
        con.execute('INSERT INTO suite_diagnostic_repairs VALUES (?,?)',
                    (source, json.dumps(receipt, sort_keys=True)))
        handoffs.save(con, source, row['issue_id'], 'diagnose_cto' if artifact_mode else 'diagnose',
                      route['cto'] if artifact_mode else route['techlead'], data, time.time())
        return receipt
