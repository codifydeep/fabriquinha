"""Controller-only facts for the bounded failed-candidate execution ledger.

No worker endpoint or model-supplied facts. Call inside the handoff transaction;
the caller owns the controller lock and must persist dispatch intent separately.
"""
import json
try:
    from . import native,bound_failure_context,handoffs,failed_candidate_execution as execution
except ImportError:
    import native,bound_failure_context,handoffs,failed_candidate_execution as execution


def facts(con,route,data,effects):
    source=data['source_task'];issue=route['issue_id'];b=effects.b
    current=con.execute('SELECT source_task,stage,data FROM delivery_handoffs WHERE issue_id=? '
                        'ORDER BY updated DESC LIMIT 1',(issue,)).fetchone()
    installed=con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(issue,)).fetchone()
    if (not current or current[0]!=source or current[1]!='technical_decision_required'
            or json.loads(current[2])!=data or not installed or json.loads(installed[0])!=route
            or route.get('enabled') is not True
            or not bound_failure_context.verified_failed_diagnostic(con,source,data)):
        raise ValueError('exact current installed failed-candidate review required')
    active=con.execute("SELECT count(*) FROM native_bindings n JOIN leases l USING(request_id) "
        "WHERE n.issue_id=? AND l.status IN ('creating','starting','running','closing')",(issue,)).fetchone()[0]
    if active:raise ValueError('replan participants must be idle before author admission')
    runs=native.issue_task_runs(effects.settings,issue)
    authors=[r for r in runs if r.get('agent_id')==route['author']]
    if (not authors or max(authors,key=lambda r:(r.get('created_at') or '',r['id']))['id']!=source
            or any(r.get('status') in ('queued','dispatched','running') for r in runs)):
        raise ValueError('latest failed author and closed native participants required')
    plan=data.get('failed_candidate_plan') or {};peer=data.get('failed_candidate_plan_review') or {}
    if (not all(k in plan for k in ('cto_task','proposal','read_paths','edit_files'))
            or not all(k in peer for k in ('techlead_task','decision'))):
        raise ValueError('completed independent technical replan required')
    tasks={}
    for task,actor,status in ((source,route['author'],'failed'),
            (plan['cto_task'],route['cto'],'completed'),(peer['techlead_task'],route['techlead'],'completed')):
        record=native.task_record(effects.settings,task,actor)
        if (record.get('id')!=task or record.get('agent_id')!=actor
                or record.get('issue_id')!=issue or record.get('status')!=status):
            raise ValueError('exact native author and independent planning identities required')
        tasks[task]=record
    for task,decision in ((plan['cto_task'],plan['proposal']),(peer['techlead_task'],peer['decision'])):
        if effects.decision(tasks[task])!=decision:
            raise ValueError('native technical decision drift')
        reads=effects.read_evidence(tasks[task])
        if not isinstance(reads,dict) or any(
                not isinstance(reads.get(p),dict) or reads[p].get('lines',0)<=0
                or reads[p].get('lines')!=reads[p].get('total_lines') for p in plan['read_paths']):
            raise ValueError('complete observed independent candidate reads required')
    scope=effects.author_edit_scope(route)
    if scope!=plan['edit_files']:raise ValueError('installed author edit scope changed')
    proof=data['failed_execution_diagnostic'];volume=proof['volume']
    labels=(b.docker('GET','/volumes/'+volume) or {}).get('Labels',{})
    if labels.get('delivery-kit.owner')!=b.OWNER or labels.get('delivery-kit.source-task')!=source:
        raise ValueError('controller-owned failed snapshot required')
    red=effects.test_first_red(source,diagnostic=True)
    if not red or not isinstance(red.get('red'),dict):raise ValueError('durable historical Red required')
    inventory=execution.validator_inventory(con,source,volume,b.OFFLINE_IMAGE,red['red'],scope)
    previous=[]
    for row in con.execute('SELECT s.task_id,s.volume FROM snapshots s '
            'JOIN delivery_handoffs h ON h.source_task=s.task_id '
            'WHERE h.issue_id=? AND s.task_id<>? AND s.status=?',(issue,source,'complete')):
        record=native.task_record(effects.settings,row[0],route['author'])
        if record.get('agent_id')!=route['author'] or record.get('issue_id')!=issue:continue
        old=execution.validator_inventory(con,row[0],row[1],b.OFFLINE_IMAGE,red['red'],scope)
        previous.append(old['product_sha256'])
    count=handoffs.repeated_corrections(con,issue,data)
    if count<2 or len(previous)<count:
        raise ValueError('complete snapshot inventory of exhausted correction history required')
    return dict(inventory,source_task=source,issue_id=issue,contract_sha256=route['contract_sha256'],
        previous_product_sha256=previous,volume=volume,source_status='failed',diagnostic_only=True,
        baseline_tests_intact=True,frozen_tests_intact=True,independent_tasks_verified=True,
        active_leases=active,identical_corrections=count)


def admit(con,route,data,effects):
    """Produce ledger authority only after all external facts are verified."""
    return execution.register(con,route,data,facts(con,route,data,effects))
