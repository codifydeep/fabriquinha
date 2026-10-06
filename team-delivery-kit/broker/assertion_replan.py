"""One source-bound CTO replan after deterministic test-review invalidation."""
import hashlib
import json
import re
import time

try:
    import candidate_qualification as qualification
except ImportError:
    from broker import candidate_qualification as qualification


def initialize(con):
    con.execute('CREATE TABLE IF NOT EXISTS assertion_replans(source_task TEXT PRIMARY KEY,config TEXT,state TEXT)')


def validate_result(config, task, decision, reads):
    qualification.validate_semantic_checks(decision, config['proof'])
    if decision.get('action') != 'request_test_revision' or decision.get('optional_files') != []:
        raise ValueError('no qualified test-only replan')
    paths = ['/evidence/candidate/' + f for f in config['required_files']]
    if (task.get('agent_id') != config['cto'] or task.get('status') != 'completed'
            or task.get('id') == config['prior_decision_task']
            or any(p not in reads or type(reads[p].get('lines')) is not int or reads[p]['lines'] <= 0
                   or reads[p]['lines'] != reads[p].get('total_lines') for p in paths)):
        raise ValueError('new CTO task and complete source reads required')
    return {'version': 'complete-source-replan-v1', 'issue_id': config['issue_id'],
            'source_task': config['source_task'], 'decision_task': task['id'],
            'output_sha256': config['output_sha256'], 'baseline_edits_allowed': False,
            'read_contract': 'complete-lines-v2', 'required_read_paths': paths,
            'read_evidence': {p: reads[p] for p in paths},
            'experiment_sha256': qualification.experiment_hash(config['proof'])}


def validated_record(data):
    record = data.get('assertion_replan') or {}
    if record.get('stage') != 'qualified':
        raise ValueError('qualified assertion replan required')
    config, task, decision = record['config'], record['task'], record['decision']
    certificate = validate_result(config, task, decision, record['reads'])
    if (certificate != data.get('technical_replan_certificate')
            or task['id'] != (data.get('test_revision_proposal') or {}).get('decision_task')
            or config['source_task'] != data.get('source_task')
            or config['proof'] != data.get('candidate_assertion_check')):
        raise ValueError('assertion replan binding drift')
    return config['proof']


def register(broker, payload):
    if (not isinstance(payload, dict) or set(payload) != {'source_task'}
            or not isinstance(payload['source_task'], str)
            or not re.fullmatch(r'[a-f0-9-]{36}', payload['source_task'])):
        raise ValueError('exact source required')
    try: import native
    except ImportError: from broker import native
    with broker.LOCK, broker.db() as con:
        initialize(con)
        prior = con.execute('SELECT state FROM assertion_replans WHERE source_task=?', (payload['source_task'],)).fetchone()
        if prior:
            return {'already_registered': True, **json.loads(prior[0])}
        row = con.execute('SELECT * FROM delivery_handoffs WHERE source_task=?', (payload['source_task'],)).fetchone()
        if not row or row['stage'] != 'technical_decision_required':
            raise ValueError('technical incident required')
        data = json.loads(row['data'])
        route = json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?', (row['issue_id'],)).fetchone()[0])
        latest = con.execute('SELECT source_task FROM delivery_handoffs WHERE issue_id=? ORDER BY updated DESC LIMIT 1', (row['issue_id'],)).fetchone()[0]
        proof = data.get('candidate_assertion_check') or {}
        invalidation = data.get('invalidated_test_review') or {}
        if (latest != payload['source_task'] or route['enabled'] or row['owner'] != route['cto']
                or invalidation.get('status') != 'approval_invalidated_not_repaired'
                or invalidation.get('candidate_check') != proof or not proof.get('contradictions')
                or con.execute("SELECT 1 FROM leases WHERE status IN ('creating','running')").fetchone()):
            raise ValueError('current paused idle invalidated test review required')
        red = json.loads(con.execute('SELECT receipt FROM test_first_red WHERE issue_id=?', (row['issue_id'],)).fetchone()[0])
        if proof['manifest_sha256'] != red['red']['manifest_sha256']:
            raise ValueError('candidate check not bound to current Red')
        failure = data['validation_failure']
        snapshot = con.execute('SELECT volume FROM snapshots WHERE task_id=? AND status=?', (payload['source_task'], 'complete')).fetchone()
        if not snapshot or snapshot[0] != failure['volume']:
            raise ValueError('failed implementation snapshot required')
        settings = json.loads((broker.STATE / 'native.json').read_text())
        runs = native.issue_task_runs(settings, row['issue_id'])
        if any(r.get('status') in ('queued', 'running') for r in runs):
            raise ValueError('idle native tasks required')
        old = next((r for r in runs if r['id'] == data.get('recipient_task')), None)
        if not old or old.get('status') != 'completed' or old.get('agent_id') != route['cto']:
            raise ValueError('prior completed CTO diagnosis required')
        requirements = native.issue_record(settings, row['issue_id'])['description'].split('\nCTO-SPONSORED NEW TEST REVISION:', 1)[0]
        if not 1 <= len(requirements) <= 2200 or len(proof['facts']) > 16:
            raise ValueError('split oversized technical replan')
        config = {'source_task': payload['source_task'], 'issue_id': row['issue_id'], 'cto': route['cto'],
            'contract_sha256': route['contract_sha256'], 'volume': snapshot[0], 'proof': proof,
            'prior_decision_task': old['id'], 'output_sha256': failure['output_sha256'],
            'required_files': sorted(set(route['test_first_files']) | set(failure['diagnostic_read_files'])),
            'requirements': requirements}
        con.execute('INSERT INTO assertion_replans VALUES (?,?,?)',
                    (payload['source_task'], json.dumps(config, sort_keys=True), json.dumps({'stage': 'pending'})))
        return {'source_task': payload['source_task'], 'stage': 'pending'}


def advance(config, state, runs, effects):
    if state['stage'] != 'pending':
        return state
    if not state.get('wakeup_id'):
        proof = config['proof']
        note = ('DELIVERY_STRUCTURED_DECISION_V1:technical\nDELIVERY_SEMANTIC_CHECKS_V1\n'
            'CTO: replan ALL NEW assertions contradicted by this fixed Python string experiment. '
            'Read all listed immutable candidate files completely. No shell, writes, Red replay, '
            'baseline changes or delivery approval. Product must keep accent-preserving casefold '
            'substring semantics. Previous test review was invalidated, not evidence of correctness.\n'
            'Requirements: ' + config['requirements'] + '\nExperiment SHA256: '
            + qualification.experiment_hash(proof) + '\n'
            'Facts [index,line,query,title,casefold_substring]: '
            + json.dumps([[i,f['query_line'],f['query'],f['title'],f['casefold_substring']]
                          for i,f in enumerate(proof['facts'])], ensure_ascii=False, separators=(',', ':'))
            + '\nContradictory assertion lines: ' + json.dumps([f['query_line'] for f in proof['contradictions']])
            + '\nReturn ONLY JSON action(request_test_revision or escalate_cto),reason<=1200 chars,'
            'optional_files=[],experiment_sha256,semantic_checks(one {fact_index,casefold_substring} '
            'per fact). A request sponsors a targeted NEW-test revision, not implementation. '
            'Preserve true Unicode matches and genuine nonmatches; do not invent accent stripping.\n'
            + ''.join('DELIVERY_REVIEW_READ_PATH:/evidence/candidate/' + f + '\n' for f in config['required_files']))
        marker = hashlib.sha256((config['source_task'] + ':assertion-replan:' + qualification.experiment_hash(proof)).encode()).hexdigest()
        if len(note) + 100 > 4000:
            return {**state, 'stage': 'blocked', 'reason': 'split replan context'}
        wake = effects.ensure_wakeup(config['issue_id'], config['cto'], config['prior_decision_task'], marker,
                                     note, allow_create=effects.remaining_calls() >= 8)
        return {**state, 'wakeup_id': wake['id'], 'at': time.time()} if wake else state
    tasks = [r for r in runs if r.get('agent_id') == config['cto'] and r.get('wakeup_id') == state['wakeup_id']]
    if len(tasks) > 1:
        return {**state, 'stage': 'blocked', 'reason': 'duplicate CTO recipient'}
    if not tasks or tasks[0].get('status') in ('queued','running'):
        return ({**state, 'stage': 'blocked', 'reason': 'CTO deadline'} if time.time()-state['at'] > 1800 else state)
    task = tasks[0]
    try:
        decision, reads = effects.decision(task), effects.read_evidence(task)
        certificate = validate_result(config, task, decision, reads)
        return {**state, 'stage': 'qualified', 'task': {k: task[k] for k in ('id','agent_id','status')},
                'decision': decision, 'reads': reads, 'certificate': certificate}
    except (ValueError, KeyError, TypeError) as error:
        return {**state, 'stage': 'blocked', 'reason': str(error), 'task_id': task['id']}


def mounts(broker, binding):
    try: import native
    except ImportError: from broker import native
    with broker.db() as con:
        initialize(con)
        rows = con.execute('SELECT config,state FROM assertion_replans').fetchall()
    for row in rows:
        config, state = json.loads(row[0]), json.loads(row[1])
        if config['issue_id'] != binding['issue_id'] or config['cto'] != binding['agent_id'] or state['stage'] != 'pending' or not state.get('wakeup_id'):
            continue
        with broker.db() as con:
            bound = con.execute('SELECT task_id FROM native_bindings WHERE request_id=?', (binding['request_id'],)).fetchone()
        if not bound:
            raise ValueError('replan native binding missing')
        task = native.task_record(json.loads((broker.STATE/'native.json').read_text()), bound[0], binding['agent_id'])
        if task.get('wakeup_id') != state['wakeup_id']:
            continue
        volume = broker.docker('GET', '/volumes/' + config['volume'])
        labels = volume.get('Labels', {}) if volume else {}
        if labels.get('delivery-kit.owner') != broker.OWNER or labels.get('delivery-kit.source-task') != config['source_task']:
            raise ValueError('replan snapshot identity mismatch')
        return [{'Type': 'volume', 'Source': config['volume'], 'Target': '/evidence/candidate', 'ReadOnly': True}]
    return []


def tick(broker):
    try: import native, handoffs
    except ImportError: from broker import native, handoffs
    settings = json.loads((broker.STATE/'native.json').read_text())
    effects = broker.handoff_runtime.Effects(broker, settings)
    with broker.db() as con:
        initialize(con)
        rows = con.execute('SELECT * FROM assertion_replans').fetchall()
    for row in rows:
        config, state = json.loads(row['config']), json.loads(row['state'])
        if state['stage'] != 'pending':
            continue
        with broker.LOCK, broker.db() as con:
            current = con.execute('SELECT * FROM delivery_handoffs WHERE source_task=?', (config['source_task'],)).fetchone()
            route = json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?', (config['issue_id'],)).fetchone()[0])
            data = json.loads(current['data'])
            if route['enabled'] or route['contract_sha256'] != config['contract_sha256'] or data.get('candidate_assertion_check') != config['proof']:
                changed = {**state, 'stage': 'blocked', 'reason': 'replan state drift'}
            else:
                changed = advance(config, state, native.issue_task_runs(settings, config['issue_id']), effects)
            con.execute('UPDATE assertion_replans SET state=? WHERE source_task=?', (json.dumps(changed, sort_keys=True), config['source_task']))
            if changed['stage'] == 'qualified':
                data.update(assertion_replan={**changed, 'config': config}, technical_replan_certificate=changed['certificate'],
                    decision=changed['decision'], test_revision_proposal={'decision_task': changed['task']['id'],
                        'source_task': config['source_task'], 'output_sha256': config['output_sha256'],
                        'reason': 'Correct all controller-verified NEW assertion contradictions, preserving coverage.',
                        'new_test_files': route['test_first_files']}, target=config['cto'])
                handoffs.save(con, config['source_task'], config['issue_id'], 'test_revision_required', route['reviewer'], data, time.time())
            elif changed['stage'] == 'blocked':
                data.update(assertion_replan_failure=changed, required_action='resolve_blocked_source_bound_replan_without_identical_retry')
                handoffs.save(con, config['source_task'], config['issue_id'], 'technical_decision_required', config['cto'], data, time.time())
