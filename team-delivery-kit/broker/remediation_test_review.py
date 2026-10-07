"""Bind R1 review to both immutable deliveries, without a recursive child."""
import json
try:
    import remediation_runtime_guard as guard
    import test_revision_review as revision
    from technical_remediation_plan import digest
except ImportError:
    from broker import remediation_runtime_guard as guard
    from broker import test_revision_review as revision
    from broker.technical_remediation_plan import digest


def config(b, issue):
    value = guard.qualified(b, issue)
    if value is None:
        raise ValueError('registered remediation R1 required')
    guard.seed_source(b, issue)  # Live immutable source-volume identity.
    with b.db() as con:
        route = json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?', (issue,)).fetchone()[0])
        source = json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?', (value['source_issue'],)).fetchone()[0])
        old_row = con.execute('SELECT receipt FROM test_first_red WHERE issue_id=?', (value['source_issue'],)).fetchone()
    if value.get('amendment'):
        try:import remediation_red_reference as references
        except ImportError:from broker import remediation_red_reference as references
        inherited=references.qualified(b,value['source_issue'])
        if not inherited or inherited['red']!=value['amendment']['seed_red']:
            raise ValueError('exact unchanged inherited amendment Red required')
        old=inherited['red'];origin=inherited['origin_issue']
    else:
        if not old_row:raise ValueError('preserved historical Red required')
        old=json.loads(old_row[0]);origin=value['source_issue']
    seed = value['previous_new_test_delivery']
    if (old.get('issue_id') != origin
            or any(old.get(k) != seed[k] for k in ('task_id', 'volume'))
            or any(old.get('red', {}).get(k) != seed[k] for k in ('manifest_sha256', 'test_sha256'))
            or old['red'].get('evidence_version') != 2
            or old['red'].get('base_manifest_sha256') != value['base']['manifest_sha256']
            or old['red'].get('baseline_test_sha256') != guard.lookup(b, issue)[2]['preparation']['proof']['baseline_test_sha256']
            or route.get('techlead') != source.get('techlead')
            or route.get('cto') != source.get('cto')
            or source.get('author') != route['author']
            or source.get('contract_sha256') != value['contract_sha256']
            or len({route['author'], route.get('techlead'), route.get('cto')}) != 3
            or not route.get('techlead') or not route.get('cto')):
        raise ValueError('same-author independent historical review lineage required')
    return dict(reviewer=route['techlead'], base_sha=value['base']['base_sha'], old_red=old,
        seed_previous_tests=True, seeded_edit_required=True, remediation_run_id=value['run_id'],
        remediation_execution_sha256=digest(value), remediation_plan_sha256=value['plan_sha256'],
        reason='R1 of independently approved recovery plan ' + value['plan_sha256'] +
               ': repair the existing NEW-test harness without removing methods, assertions or behavioral coverage. '
               'Review all approved card criteria. This review cannot unlock product edits on R1.')


def install(b, issue):
    """Controller-only immutable policy registration; not a Red or grant."""
    with b.LOCK:
        expected = config(b, issue)
        with b.db() as con:
            revision.initialize(con)
            if (con.execute("SELECT 1 FROM sqlite_master WHERE name='leases'").fetchone()
                    and con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone()):
                raise ValueError('idle review-policy registration required')
            previous = con.execute('SELECT parent_issue,config FROM test_revision_trials WHERE issue_id=?', (issue,)).fetchone()
            if previous:
                if previous[0] is not None or json.loads(previous[1]) != expected:
                    raise ValueError('immutable remediation review policy drift')
            else:
                con.execute('INSERT INTO test_revision_trials VALUES (?,?,?,?)', (issue, None, json.dumps(expected, sort_keys=True), '{}'))
        return expected


def verify(b, issue, route, red, effects):
    """Qualify an actual new controller Red before the ordinary immutable review."""
    expected = config(b, issue)
    try:import harness_qualification
    except ImportError:from broker import harness_qualification
    harness_qualification.require(b,issue,red)
    with b.db() as con:
        revision.initialize(con)
        installed = con.execute('SELECT parent_issue,config,state FROM test_revision_trials WHERE issue_id=?', (issue,)).fetchone()
        actual = con.execute('SELECT receipt FROM test_first_red WHERE issue_id=?', (issue,)).fetchone()
        current_route = con.execute('SELECT config FROM delivery_routes WHERE issue_id=?', (issue,)).fetchone()
    if (not installed or installed[0] is not None or json.loads(installed[1]) != expected
            or not actual or json.loads(actual[0]) != red or json.loads(current_route[0]) != route
            or not callable(getattr(effects, 'test_review_report', None))):
        raise ValueError('installed historical comparison policy and actual new Red required')
    facts = red.get('red', {}); old = expected['old_red']
    if (red.get('issue_id') != issue or red.get('task_id') == old['task_id']
            or red.get('volume') == old['volume'] or not red.get('task_id') or not red.get('volume')
            or facts.get('manifest_sha256') == old['red']['manifest_sha256']
            or facts.get('test_sha256') == old['red']['test_sha256']
            or set(facts.get('test_sha256', {})) != set(old['red']['test_sha256'])
            or facts.get('evidence_version') != 2 or facts.get('exit_code') != 1
            or type(facts.get('test_count')) is not int or facts['test_count'] < old['red']['test_count']
            or any(facts.get(k) != old['red'][k] for k in
                   ('command', 'test_image', 'base_manifest_sha256', 'baseline_test_sha256'))):
        raise ValueError('fresh full-suite Red on unchanged original baseline required')
    info = b.docker('GET', '/volumes/' + red['volume'])
    labels = info.get('Labels', {}) if info else {}
    if labels.get('delivery-kit.owner') != b.OWNER or labels.get('delivery-kit.test-first-task') != red['task_id']:
        raise ValueError('new immutable Red snapshot ownership drift')
    state = json.loads(installed[2])
    if state.get('evidence_policy'):
        comparison = state.get('comparison', {})
        validate_comparison(expected, red, comparison)
    if state.get('status') == 'approved':
        decision = state.get('decision', {})
        if (state.get('evidence_policy') != 1 or state.get('read_contract') != 'complete-lines-v2'
                or state.get('source_task') != red['task_id'] or state.get('candidate_volume') != red['volume']
                or state.get('previous_volume') != old['volume']
                or state.get('manifest_sha256') != facts['manifest_sha256']
                or decision.get('action') != 'approve_test_revision'
                or decision.get('manifest_sha256') != facts['manifest_sha256']
                or not state.get('review_task') or state['review_task'] == red['task_id']):
            raise ValueError('exact independent approval binding required')
        reads = effects.read_evidence({'id': state['review_task']})
        paths = ['/evidence/' + tree + '/' + name for tree in ('candidate', 'previous') for name in facts['test_sha256']]
        if any(type(reads.get(p, {}).get('lines')) is not int or reads[p]['lines'] <= 0
               or reads[p]['lines'] != reads[p].get('total_lines') for p in paths):
            raise ValueError('complete actual reads of both deliveries required')
        revision.validate_evidence(b, route, state, decision)
    return expected


def validate_comparison(config, red, summary):
    old = config['old_red']['red']; new = red['red']
    if (summary.get('candidate_manifest') != new['manifest_sha256']
            or summary.get('previous_manifest') != old['manifest_sha256']
            or set(summary.get('files', {})) != set(new['test_sha256'])):
        raise ValueError('exact complete two-delivery comparison required')
    for name, facts in summary['files'].items():
        if (facts.get('candidate_sha256') != new['test_sha256'][name]
                or facts.get('previous_sha256') != old['test_sha256'][name]
                or not isinstance(facts.get('removed_methods'), list)
                or not isinstance(facts.get('removed_assertion_ast'), dict)):
            raise ValueError('hash-bound structural comparison required')


def record_gate(b, route, red, effects):
    """Complete only R1; never fall through to same-card product implementation."""
    issue = route['issue_id']
    if guard.lookup(b, issue) is None:
        return False
    verify(b, issue, route, red, effects)
    with b.LOCK, b.db() as con:
        source, value, state = guard.lookup(b, issue)
        review = json.loads(con.execute('SELECT state FROM test_revision_trials WHERE issue_id=?', (issue,)).fetchone()[0])
        if review.get('status') != 'approved':
            raise ValueError('actual independent R1 approval required')
        receipt = dict(operation='immutable_remediation_r1_gate_v1',run_id=value['run_id'],
            execution_contract_sha256=digest(value),red=red,
            review_task=review['review_task'],review_decision=review['decision'],
            comparison_sha256=digest(review['comparison']),
            product_execution_authorized=False,release_homologated=False)
        previous = state.get('r1_gate')
        if previous and previous != receipt:
            raise ValueError('immutable R1 gate drift')
        state.update(r1_gate=receipt,required_action='qualify_dependent_R2_runtime_on_frozen_R1_delivery')
        state['steps']={**state.get('steps',{}),'R1':dict(stage='approved',issue_id=issue,
                       manifest_sha256=red['red']['manifest_sha256'],review_task=review['review_task'])}
        con.execute('UPDATE remediation_executions SET state=? WHERE source_task=?', (json.dumps(state,sort_keys=True),source))
        # Keep this card immutable and prevent normal test-first re-dispatch.
        paused={**route,'enabled':False}
        con.execute('UPDATE delivery_routes SET config=? WHERE issue_id=?',(json.dumps(paused,sort_keys=True),issue))
        try:
            import handoffs
        except ImportError:
            from broker import handoffs
        import time
        handoffs.save(con,red['task_id'],issue,'remediation_r1_approved',route['techlead'],receipt,time.time())
    return True


def preserve_coverage(decision, summary):
    """A model approval cannot override detected structural regression."""
    if decision.get('action') == 'approve_test_revision' and any(
            facts.get('removed_methods') or facts.get('removed_assertion_ast')
            for facts in summary.get('files', {}).values()):
        raise ValueError('remediation approval cannot remove existing test methods or assertions')
