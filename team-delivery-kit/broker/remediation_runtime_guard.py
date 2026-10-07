"""Fail-closed R1 permissions; preparation is never product authority."""
import json
try:
    import remediation_preparation as preparation
    import technical_remediation_plan as planning
except ImportError:
    from broker import remediation_preparation as preparation
    from broker import technical_remediation_plan as planning


def lookup(b, issue):
    with b.db() as con:
        if not con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='remediation_executions'").fetchone():
            return None  # Unrelated legacy executions retain their existing policy.
        matches = []
        for row in con.execute('SELECT source_task,contract,state FROM remediation_executions'):
            source, value, state = row[0], json.loads(row[1]), json.loads(row[2])
            if state.get('issue_id') == issue:
                matches.append((source, value, state))
        if not matches:
            return None
        if len(matches) != 1:
            raise ValueError('ambiguous remediation issue binding')
        return matches[0]


def qualified(b, issue):
    row = lookup(b, issue)
    if row is None:
        return None
    source, value, state = row
    step = value['steps'][0]
    if (state.get('stage') != 'r1_base_qualified'
            or state.get('execution_authorized') is not False
            or state.get('contract_sha256') != planning.digest(value)
            or source != value['source_task'] or value.get('original_depth') != 2
            or step.get('id') != 'R1' or step.get('edit_scope') != 'new_tests_only'
            or not step.get('editable_files')
            or set(step['editable_files']) != set(value['previous_new_test_delivery']['test_sha256'])
            or value.get('baseline_edits_allowed') is not False
            or value.get('historical_snapshots_editable') is not False
            or value.get('release_homologated') is not False):
        raise ValueError('qualified immutable tests-only remediation required')
    preparation.validate_proof(value, state['preparation']['proof'])
    with b.db() as con:
        route_row = con.execute('SELECT config FROM delivery_routes WHERE issue_id=?', (issue,)).fetchone()
        if not route_row:
            raise ValueError('remediation route missing; no worker authority')
        route = json.loads(route_row[0])
    if (route.get('issue_id') != issue or route.get('author') != step['owner']
            or route.get('contract_sha256') != value['contract_sha256']
            or route.get('test_first') is not True
            or set(route.get('test_first_files', [])) != set(step['editable_files'])):
        raise ValueError('remediation runtime scope drift')
    expected = {**value['base'], 'volume': b.PREFIX + '-base-' + issue}
    if b.issue_base(issue) != {**expected, 'issue_id': issue}:
        raise ValueError('remediation original base binding drift')
    return value


def phase(b, issue):
    return 'tests_only' if qualified(b, issue) is not None else None


def seed_source(b, issue):
    value = qualified(b, issue)
    if value is None:
        return None
    seed = value['previous_new_test_delivery']
    info = b.docker('GET', '/volumes/' + seed['volume'])
    labels = info.get('Labels', {}) if info else {}
    if (labels.get('delivery-kit.owner') != b.OWNER
            or labels.get('delivery-kit.test-first-task') != seed['task_id']):
        raise ValueError('remediation preserved seed ownership drift')
    return dict(mount=dict(Type='volume', Source=seed['volume'], Target='/previous', ReadOnly=True),
                selection={key: seed[key] for key in ('manifest_sha256', 'test_sha256')})


def require_historical_review(b, issue, route=None, red=None, effects=None):
    if lookup(b, issue) is not None:
        if route is None or red is None or effects is None:
            raise ValueError('remediation historical independent review adapter required')
        try:
            import remediation_test_review
        except ImportError:
            from broker import remediation_test_review
        return remediation_test_review.verify(b, issue, route, red, effects)
