"""Explicit R2 -> approved R1 Red reference; never invent a local Red receipt."""
import json
try:
    import remediation_author_context as context
    import remediation_test_review as review
    from technical_remediation_plan import digest
except ImportError:
    from broker import remediation_author_context as context
    from broker import remediation_test_review as review
    from broker.technical_remediation_plan import digest


def initialize(con):
    con.execute('CREATE TABLE IF NOT EXISTS remediation_red_references(issue_id TEXT PRIMARY KEY,source_task TEXT,body TEXT)')


def binding(b, issue, source):
    with b.db() as con:
        row=con.execute('SELECT contract,state FROM remediation_executions WHERE source_task=?',(source,)).fetchone()
        route_row=con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(issue,)).fetchone()
        if not row or not route_row:raise ValueError('registered recovery and R2 route required')
        value,state=map(json.loads,row); route=json.loads(route_row[0]); inputs=context.product_input(value,state)
        origin=inputs['origin_issue']
        r1_row=con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(origin,)).fetchone()
        if not r1_row:raise ValueError('original R1 route required')
        r1=json.loads(r1_row[0])
        paths=sorted(r[0] for r in con.execute('SELECT path FROM issue_editables WHERE issue_id=?',(issue,)))
        local=con.execute('SELECT receipt FROM test_first_red WHERE issue_id=?',(issue,)).fetchone()
        actual_red=con.execute('SELECT receipt FROM test_first_red WHERE issue_id=?',(origin,)).fetchone()
        approved=con.execute('SELECT config,state FROM test_revision_trials WHERE issue_id=?',(origin,)).fetchone()
    policy,verdict_state=map(json.loads,approved) if approved else ({},{})
    old=policy.get('old_red',{}); seed=value['previous_new_test_delivery']
    if (issue in (origin,value['source_issue'],value['root_issue']) or local
            or not actual_red or json.loads(actual_red[0])!=inputs['red']
            or r1.get('enabled') is not False or policy.get('reviewer')!=r1.get('techlead')
            or policy.get('initial_review') or policy.get('remediation_execution_sha256')!=digest(value)
            or any(old.get(k)!=seed[k] for k in ('task_id','volume'))
            or any(old.get('red',{}).get(k)!=seed[k] for k in ('manifest_sha256','test_sha256'))
            or verdict_state.get('status')!='approved'
            or verdict_state.get('read_contract')!='complete-lines-v2'
            or verdict_state.get('previous_volume')!=seed['volume']
            or verdict_state.get('review_task')!=state['r1_gate']['review_task']
            or verdict_state.get('decision')!=state['r1_gate']['review_decision']
            or verdict_state.get('manifest_sha256')!=inputs['red']['red']['manifest_sha256']
            or verdict_state.get('source_task')!=inputs['red']['task_id']
            or verdict_state.get('candidate_volume')!=inputs['red']['volume']
            or route.get('issue_id')!=issue or 'test_first' in route
            or route.get('author')!=value['steps'][1]['owner']
            or any(route.get(k)!=r1.get(k) for k in ('author','reviewer','techlead','cto','contract_sha256'))
            or route.get('contract_sha256')!=value['contract_sha256']
            or len({route.get(k) for k in ('author','reviewer','techlead','cto')})!=4
            or any(not route.get(k) for k in ('author','reviewer','techlead','cto'))
            or paths!=sorted('/workspace/'+p for p in inputs['editable_files'])):
        raise ValueError('independent product-only R2 with unchanged R1 origin required')
    base=b.issue_base(issue)
    if (base.get('issue_id')!=issue or base.get('volume')!=b.PREFIX+'-base-'+issue
            or any(base.get(k)!=value['base'][k] for k in ('base_sha','manifest_sha256'))):
        raise ValueError('R2 must retain original Git base, not treat Red as a new baseline')
    expected={**inputs,'issue_id':issue,'author':route['author'],'source_task':source,
        'execution_contract_sha256':digest(value),
        'route_sha256':digest({k:v for k,v in route.items() if k!='enabled'})}
    return expected,r1,route


def register(b,issue,source,effects):
    """Controller-only admission after independently verified R1 approval."""
    with b.LOCK:
        expected,r1,route=binding(b,issue,source)
        if route.get('enabled') is not False:raise ValueError('paused R2 registration required')
        review.verify(b,expected['origin_issue'],r1,expected['red'],effects)
        with b.db() as con:
            initialize(con)
            if con.execute("SELECT 1 FROM native_bindings n JOIN leases l USING(request_id) "
                    "WHERE n.issue_id IN (?,?) AND l.status IN ('creating','starting','running','closing')",
                    (issue,expected['origin_issue'])).fetchone():
                raise ValueError('R1/R2 dependency leases must close before reference registration')
            old=con.execute('SELECT source_task,body FROM remediation_red_references WHERE issue_id=?',(issue,)).fetchone()
            if old:
                if old[0]!=source or json.loads(old[1])!=expected:raise ValueError('immutable R2 reference drift')
            else:
                con.execute('INSERT INTO remediation_red_references VALUES (?,?,?)',(issue,source,json.dumps(expected,sort_keys=True)))
        return expected


def qualified(b,issue):
    with b.db() as con:
        if not con.execute("SELECT 1 FROM sqlite_master WHERE name='remediation_red_references'").fetchone():return None
        row=con.execute('SELECT source_task,body FROM remediation_red_references WHERE issue_id=?',(issue,)).fetchone()
    if not row:return None
    expected,r1,route=binding(b,issue,row[0])
    if json.loads(row[1])!=expected:raise ValueError('R2 reference or approved dependency drift')
    red=expected['red']
    actual=b.docker('GET','/volumes/'+red['volume']);labels=actual.get('Labels',{}) if actual else {}
    if labels.get('delivery-kit.owner')!=b.OWNER or labels.get('delivery-kit.test-first-task')!=red['task_id']:
        raise ValueError('R1 Red volume ownership drift')
    return expected


def phase(b,issue):
    return 'implement_after_red' if qualified(b,issue) is not None else None


def seed_source(b,issue):
    value=qualified(b,issue)
    if value is None:return None
    red=value['red']
    return dict(mount=dict(Type='volume',Source=red['volume'],Target='/previous',ReadOnly=True),
                selection={k:red['red'][k] for k in ('manifest_sha256','test_sha256')})


def task_red(b,task,*,diagnostic=False):
    """Read-only provenance; paused routes require explicit diagnostic use.

    The diagnostic result cannot qualify delivery or dispatch. Normal callers
    still require an enabled route; role, closed lease and lineage never relax.
    """
    if type(diagnostic) is not bool:raise ValueError('explicit diagnostic mode required')
    with b.db() as con:
        if not con.execute("SELECT 1 FROM sqlite_master WHERE name='remediation_red_references'").fetchone():return None
        row=con.execute('SELECT n.issue_id,n.agent_id,n.scope,g.mode,l.status FROM native_bindings n '
            'JOIN grants g USING(request_id) JOIN leases l USING(request_id) WHERE n.task_id=? '
            'ORDER BY n.rowid DESC LIMIT 1',(task,)).fetchone()
    if not row:return None
    value=qualified(b,row[0])
    if value is None:return None
    with b.db() as con:route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(row[0],)).fetchone()[0])
    if (row[1]!=value['author'] or row[3]!='implementation' or row[4]!='closed'
            or (route.get('enabled') is not True and not diagnostic) or task==value['red']['task_id']):
        raise ValueError('closed exact R2 author execution required')
    return value['red']  # Original issue/task/scope are deliberately unchanged.
