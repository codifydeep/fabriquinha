"""Opt-in scope recovery coordinator; one persisted owner for each issue.

Registration is controller/operator-only, not a worker tool. Legacy handoffs
remain responsible until a qualifying hold is selected, and resume only after
the explicitly bound new author is admitted. No stage is delivery success.
"""
import json
import threading
import uuid
try:
    from . import product_scope_bootstrap as bootstrap,product_scope_execution as execution,product_scope_ledger as ledger
    from . import product_scope_job as materialization,product_scope_registration as registration,product_scope_author as author
    from . import validation_job,controller_maintenance
except ImportError:
    import product_scope_bootstrap as bootstrap
    import product_scope_execution as execution
    import product_scope_ledger as ledger
    import product_scope_job as materialization
    import product_scope_registration as registration
    import product_scope_author as author
    import validation_job,controller_maintenance

_tick_lock=threading.Lock()


def initialize(con):
    con.execute('CREATE TABLE IF NOT EXISTS product_scope_runs(issue_id TEXT PRIMARY KEY,config TEXT,state TEXT)')


def register(b,config):
    if (not isinstance(config,dict) or set(config)!={'issue_id','contract_sha256','enabled'}
            or str(uuid.UUID(config['issue_id']))!=config['issue_id'] or type(config['enabled']) is not bool):
        raise ValueError('exact opt-in controller scope route required')
    with b.LOCK,b.db() as con:
        initialize(con)
        row=con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(config['issue_id'],)).fetchone()
        if not row:raise ValueError('existing independently registered delivery route required')
        route=json.loads(row[0])
        if (route.get('test_first') is not True or route['contract_sha256']!=config['contract_sha256']
                or len({route['author'],route['cto'],route['techlead']})!=3
                or config['enabled'] and route.get('enabled') is not True):
            raise ValueError('unchanged test-first delivery route and independent scope roles required')
        prior=con.execute('SELECT config FROM product_scope_runs WHERE issue_id=?',(config['issue_id'],)).fetchone()
        if prior:
            before=json.loads(prior[0])
            if any(before[k]!=config[k] for k in ('issue_id','contract_sha256')):
                raise ValueError('scope recovery route immutable except pause')
            con.execute('UPDATE product_scope_runs SET config=? WHERE issue_id=?',(ledger.encoded(config),config['issue_id']))
        else:
            state=dict(stage='waiting_for_hold',owner=route['cto'],delivery_approval=False)
            con.execute('INSERT INTO product_scope_runs VALUES (?,?,?)',
                        (config['issue_id'],ledger.encoded(config),ledger.encoded(state)))
    return config


def save(b,issue,before,after):
    with b.LOCK,b.db() as con:
        changed=con.execute('UPDATE product_scope_runs SET state=? WHERE issue_id=? AND state=?',
                            (ledger.encoded(after),issue,ledger.encoded(before)))
        if changed.rowcount!=1:raise ValueError('scope pipeline changed during observation')
    return after


def owned(con):
    if not con.execute("SELECT 1 FROM sqlite_master WHERE name='product_scope_runs'").fetchone():return set()
    return {issue for issue,raw in con.execute('SELECT issue_id,state FROM product_scope_runs')
            if json.loads(raw)['stage'] not in ('waiting_for_hold','author_admitted')}


def step(b,config,state):
    issue=config['issue_id']
    if state['stage']=='waiting_for_hold':
        with b.db() as con:
            row=con.execute('SELECT source_task,stage,data FROM delivery_handoffs WHERE issue_id=? AND stage<>? '
                            'ORDER BY updated DESC LIMIT 1',(issue,'superseded')).fetchone()
            route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(issue,)).fetchone()[0])
        if route.get('enabled') is not True or route['contract_sha256']!=config['contract_sha256']:
            raise ValueError('configured delivery route changed')
        if not row or row[1]!='technical_decision_required':return state
        failure=json.loads(row[2]).get('validation_failure') or {}
        if failure.get('category')!='executed_test_failure' or failure.get('source_task')!=row[0]:return state
        return save(b,issue,state,dict(state,stage='bootstrap',source_task=row[0],failure_output_sha256=failure['output_sha256']))
    if state['stage'] in ('blocked','author_admitted'):return state
    if state['stage']=='bootstrap':
        with b.db() as con:
            row=con.execute('SELECT source_task,stage,data FROM delivery_handoffs WHERE issue_id=? AND stage<>? '
                            'ORDER BY updated DESC LIMIT 1',(issue,'superseded')).fetchone()
        if (not row or row[0]!=state['source_task'] or row[1]!='technical_decision_required'
                or json.loads(row[2]).get('validation_failure',{}).get('output_sha256')!=state['failure_output_sha256']):
            raise ValueError('selected scope sponsor changed before bootstrap')
        plan=bootstrap.prepare(b,issue)
        return save(b,issue,state,dict(state,stage='scope_plan',plan_key=plan['key']))
    if state['stage']!='scope_plan':raise ValueError('known scope pipeline stage required')
    with b.db() as con:plan=ledger.load(con,state['plan_key'])
    if (plan['context']['issue_id']!=issue or plan['context']['source_task']!=state['source_task']
            or plan['context']['failure_output_sha256']!=state['failure_output_sha256']
            or plan['context']['contract_sha256']!=config['contract_sha256']):
        raise ValueError('exact immutable pipeline plan required')
    if plan['stage'] in ('awaiting_proposal','awaiting_review'):
        execution.tick(b,plan['key'])
    elif plan['stage'] in ('blocked','changes_requested'):
        return save(b,issue,state,dict(state,stage='blocked',incident=dict(category='scope_plan_not_approved',
            owner=plan['context']['cto'],next_action='diagnose_exact_plan',automatic_retry=False)))
    elif plan['stage']=='plan_approved':
        if plan.get('materialization',{}).get('stage')!='complete':
            materialization.tick(b,plan['key'])
        elif plan.get('registration',{}).get('stage')!='complete':
            registration.tick(b,plan['key'])
        else:
            result=author.tick(b,plan['key'])
            dispatch=result.get('dispatch',{}).get('author',{})
            if dispatch.get('stage')=='admitted':
                return save(b,issue,state,dict(state,stage='author_admitted',author_task=dispatch['task_id'],
                                              owner=plan['context']['author']))
            if dispatch.get('stage')=='blocked':
                return save(b,issue,state,dict(state,stage='blocked',incident=dispatch['incident']))
    else:raise ValueError('known scope plan stage required')
    with b.db() as con:current=ledger.load(con,plan['key'])
    for phase in ('materialization','registration'):
        if current.get(phase,{}).get('stage')=='blocked':
            return save(b,issue,state,dict(state,stage='blocked',incident=current[phase]['incident']))
    return state


def tick(b):
    with b.db() as con:
        if not con.execute("SELECT 1 FROM sqlite_master WHERE name='product_scope_runs'").fetchone():return set()
        if controller_maintenance.current(con):return owned(con)
        rows=list(con.execute('SELECT config,state FROM product_scope_runs'))
    if not _tick_lock.acquire(blocking=False):
        with b.db() as con:return owned(con)
    try:
        for raw_config,raw_state in rows:
            config,state=json.loads(raw_config),json.loads(raw_state)
            if not config['enabled'] or state['stage'] in ('blocked','author_admitted'):continue
            try:step(b,config,state)
            except (validation_job.Pending,TimeoutError):
                # Existing durable job/wakeup intent remains authoritative.
                # Observe it again; do not clear its handle or create a retry.
                continue
            except (ValueError,KeyError,TypeError,OSError) as error:
                with b.db() as con:
                    current=json.loads(con.execute('SELECT state FROM product_scope_runs WHERE issue_id=?',(config['issue_id'],)).fetchone()[0])
                if current==state:
                    save(b,config['issue_id'],state,dict(state,stage='blocked',incident=dict(
                        category='scope_pipeline_infrastructure_failure' if isinstance(error,OSError) else 'scope_pipeline_precondition_rejected',
                        phase=state['stage'],error_type=type(error).__name__,owner=state['owner'],
                        next_action='diagnose_exact_scope_precondition',automatic_retry=False)))
        with b.db() as con:return owned(con)
    finally:_tick_lock.release()
