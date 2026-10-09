"""Read-only generic intake for exhausted NEW-test revisions.

Qualification creates planning data, not a worker grant or a third revision.
Historical receipts are inputs, never retroactively upgraded evidence.
"""
import json
import re
import time
from pathlib import PurePosixPath

try:
    import technical_remediation_plan as plans, suite_failure, native, handoff_runtime
except ImportError:
    from broker import technical_remediation_plan as plans, suite_failure, native, handoff_runtime


def ancestry(issue, base_sha, load_trial):
    """Derive depth from durable parent links, not a caller/environment value."""
    lineage = []
    while True:
        trial = load_trial(issue)
        if not trial or trial.get('base_sha') != base_sha:
            raise ValueError('preserved original-base revision ancestry required')
        if trial.get('initial_review') is True:
            if len(lineage) != 2 or any(k in trial for k in ('parent_issue', 'old_red', 'cto_decision')):
                raise ValueError('exactly two revisions and authentic initial root required')
            return issue, lineage
        parent = trial.get('parent_issue')
        if (not parent or parent == issue or parent in lineage or len(lineage) >= 2
                or not trial.get('cto_decision') or not trial.get('old_red')):
            raise ValueError('bounded explicit independent revision lineage required')
        lineage.append(issue)
        issue = parent


def configuration(row, route, red, base, failure, output, task, decision, reads, load_trial):
    """Pure planning qualification; live callers must verify ownership and leases."""
    data = json.loads(row['data'])
    proposal = data.get('test_revision_proposal') or {}
    diagnostic = suite_failure.derived_numeric_diagnostic(failure, output)
    files = sorted(set(route.get('test_first_files', [])) |
                   set(failure.get('diagnostic_read_files', [])))
    for path in files:
        if (not isinstance(path, str) or re.fullmatch(r'[A-Za-z0-9_./-]{1,240}', path) is None
                or PurePosixPath(path).is_absolute() or '\\' in path
                or '..' in path.split('/') or str(PurePosixPath(path)) != path):
            raise ValueError('canonical immutable source paths required')
    paths = ['/evidence/candidate/' + p for p in files]
    if (row['stage'] != 'test_revision_required' or row['source_task'] != data.get('source_task')
            or row['issue_id'] != route.get('issue_id') or data.get('source_status') != 'completed'
            or route.get('test_first') is not True
            or len({route.get(k) for k in ('author', 'reviewer', 'cto', 'techlead')}) != 4
            or any(not route.get(k) for k in ('author', 'reviewer', 'cto', 'techlead'))
            or task.get('id') != data.get('recipient_task') or task.get('id') != proposal.get('decision_task')
            or task.get('status') != 'completed' or task.get('agent_id') != route['cto']
            or task.get('issue_id') != row['issue_id'] or task.get('wakeup_id') != data.get('wakeup_id')
            or data.get('target') != route['cto'] or data.get('decision') != decision
            or decision.get('action') != 'request_test_revision' or decision.get('optional_files') != []
            or not isinstance(decision.get('reason'), str) or not 1 <= len(decision['reason']) <= 1200
            or proposal.get('reason') != decision['reason']
            or proposal.get('source_task') != row['source_task']
            or proposal.get('output_sha256') != failure['output_sha256']
            or failure != data.get('validation_failure') or failure.get('source_task') != row['source_task']
            or type(failure.get('tests_executed')) is not int or failure['tests_executed'] <= 0
            or not failure.get('failures') or not paths or len(paths) > 32
            or any(type(reads.get(p, {}).get('lines')) is not int or reads[p]['lines'] <= 0
                   or reads[p]['lines'] != reads[p].get('total_lines') for p in paths)
            or set(route['test_first_files']) != set(proposal.get('new_test_files', []))
            or set(route['test_first_files']) != set(red.get('red', {}).get('test_sha256', {}))
            or base.get('issue_id') != row['issue_id']):
        raise ValueError('exact completed independent CTO and failed frozen suite required')
    root, lineage = ancestry(row['issue_id'], base['base_sha'], load_trial)
    capsule = plans.validate_capsule(route['execution_context'])
    result = dict(source_task=row['source_task'], source_issue=row['issue_id'], root_issue=root,
        original_depth=2, revision_lineage=lineage, cto=route['cto'], reviewer=route['techlead'],
        original_author=route['author'], contract_sha256=route['contract_sha256'],
        context_sha256=capsule['sha256'], criteria=plans.criteria(capsule), base=base,
        volume=failure['volume'], required_paths=paths,
        diagnostic_task=task['id'], diagnostic_wakeup=task['wakeup_id'],
        diagnostic_read_evidence={p: reads[p] for p in paths},
        diagnostic_snapshot_kind='completed_frozen_validation',
        intake_kind='exhausted_frozen_suite_v1', historical_failure=failure,
        preserved_source_attempts=data.get('attempts'),
        experiment=dict(operation='archived_failed_suite_reference_v1',
            proof=dict(input_sha256=red['red']['test_sha256'],
                facts=dict(numeric_diagnostic=diagnostic, tests_executed=failure['tests_executed'],
                    failures=failure['failures'], test_defect_proven=False,
                    historical_tests_changed=False))))
    return json.loads(json.dumps(result))  # No mutable aliases to historical inputs.


def qualify(b, source):
    """No state writes, provider calls, test execution or permission changes."""
    with b.LOCK:
        with b.db() as con:
            if con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone():
                raise ValueError('idle exhausted-suite qualification required')
            row = con.execute('SELECT * FROM delivery_handoffs WHERE source_task=?', (source,)).fetchone()
            if not row:
                raise ValueError('current source required')
            latest = con.execute('SELECT source_task FROM delivery_handoffs WHERE issue_id=? ORDER BY updated DESC,rowid DESC LIMIT 1', (row['issue_id'],)).fetchone()
            if latest[0] != source:
                raise ValueError('superseded source cannot qualify')
            route = json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?', (row['issue_id'],)).fetchone()[0])
            red = json.loads(con.execute('SELECT receipt FROM test_first_red WHERE issue_id=?', (row['issue_id'],)).fetchone()[0])
            archived = con.execute('SELECT receipt,output FROM frozen_suite_failures WHERE task_id=?', (source,)).fetchone()
            snapshot = con.execute('SELECT volume,status FROM snapshots WHERE task_id=?', (source,)).fetchone()
            if not archived or not snapshot or snapshot['status'] != 'complete':
                raise ValueError('durable complete frozen failure required')
            failure = json.loads(archived['receipt'])
            # Handoff-only read-path annotations are not rewritten into archival evidence.
            data = json.loads(row['data'])
            projected = data.get('validation_failure') or {}
            if any(projected.get(k) != v for k, v in failure.items()) or snapshot['volume'] != failure['volume']:
                raise ValueError('archive and handoff evidence drift')
            def load_trial(issue):
                trial = con.execute('SELECT config FROM test_revision_trials WHERE issue_id=?', (issue,)).fetchone()
                return json.loads(trial[0]) if trial else None
            settings = json.loads((b.STATE / 'native.json').read_text())
            task = native.task_record(settings, data['recipient_task'], route['cto'])
            fx = handoff_runtime.Effects(b.handoff_context() if hasattr(b, 'handoff_context') else b, settings)
            author = native.task_record(settings, source, route['author'])
            bindings = con.execute('SELECT l.status FROM native_bindings n JOIN leases l USING(request_id) WHERE n.task_id=? AND n.agent_id=? AND n.issue_id=?',
                (source, route['author'], row['issue_id'])).fetchall()
            latest_author = con.execute('SELECT task_id FROM native_bindings WHERE agent_id=? AND issue_id=? ORDER BY rowid DESC LIMIT 1',
                (route['author'], row['issue_id'])).fetchone()
            if (author.get('status') != 'completed' or author.get('issue_id') != row['issue_id']
                    or len(bindings) != 1 or bindings[0][0] != 'closed'
                    or not latest_author or latest_author[0] != source
                    or any(t['status'] in ('queued', 'running', 'dispatched') for t in native.issue_task_runs(settings, row['issue_id']))):
                raise ValueError('closed completed author and idle native scope required')
            labels = (b.docker('GET', '/volumes/' + snapshot['volume']) or {}).get('Labels', {})
            if labels.get('delivery-kit.owner') != b.OWNER or labels.get('delivery-kit.source-task') != source:
                raise ValueError('controller-owned immutable snapshot required')
            value = configuration(row, route, red, b.issue_base(row['issue_id']), projected,
                archived['output'], task, fx.decision(task), fx.read_evidence(task), load_trial)
            current = con.execute('SELECT * FROM delivery_handoffs WHERE source_task=?', (source,)).fetchone()
            current_route = con.execute('SELECT config FROM delivery_routes WHERE issue_id=?', (row['issue_id'],)).fetchone()
            if (dict(current) != dict(row) or json.loads(current_route[0]) != route
                    or con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone()):
                raise ValueError('source changed during read-only qualification')
            return value


def register(b, source):
    """Atomically enter planning; repeats observe the same durable intent."""
    with b.LOCK:
        with b.db() as con:
            plans.initialize(con)
            prior = con.execute('SELECT config,state FROM technical_remediation_plans WHERE source_task=?', (source,)).fetchone()
            if prior:
                config, state = map(json.loads, prior)
                if config.get('intake_kind') != 'exhausted_frozen_suite_v1':
                    raise ValueError('foreign existing remediation registration')
                return state
            row = con.execute('SELECT * FROM delivery_handoffs WHERE source_task=?', (source,)).fetchone()
            if not row:
                raise ValueError('source handoff required')
            observed = dict(row)
            route = json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?', (row['issue_id'],)).fetchone()[0])
        value = qualify(b, source)
        state = dict(stage='issue_intent', owner=value['cto'], execution_authorized=False, release_homologated=False)
        with b.db() as con:
            current = con.execute('SELECT * FROM delivery_handoffs WHERE source_task=?', (source,)).fetchone()
            current_route = con.execute('SELECT config FROM delivery_routes WHERE issue_id=?', (value['source_issue'],)).fetchone()
            if (not current or dict(current) != observed or json.loads(current_route[0]) != route
                    or con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone()):
                raise ValueError('source changed before planning intent')
            plans.initialize(con)
            con.execute('INSERT INTO technical_remediation_plans VALUES(?,?,?)',
                (source, json.dumps(value, sort_keys=True), json.dumps(state, sort_keys=True)))
            route['enabled'] = False
            con.execute('UPDATE delivery_routes SET config=? WHERE issue_id=?', (json.dumps(route, sort_keys=True), value['source_issue']))
            data = json.loads(current['data'])
            data.update(exhausted_revision_proposal=data['test_revision_proposal'],
                technical_remediation_plan=dict(source_task=source, original_depth=2, execution_authorized=False),
                required_action='cto_propose_distinct_remediation_then_independent_techlead_review')
            plans.handoffs.save(con, source, value['source_issue'], 'technical_decision_required', value['cto'], data, time.time())
        return state
