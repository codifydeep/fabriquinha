"""Explicit immutable scope-base selection, not a worker write permission.

The controller must persist an author dispatch intent before binding. Historical
tasks and issue-wide defaults never inherit a registered scope base. Tool grants
remain a separate gate and may not exist when this binding is first created.
"""
import json
try:
    from . import product_scope_ledger as ledger, product_scope_execution as execution, product_scope_job as job
except ImportError:
    import product_scope_ledger as ledger
    import product_scope_execution as execution
    import product_scope_job as job


def initialize(con):
    con.execute('CREATE TABLE IF NOT EXISTS product_scope_task_bases '
                '(task_id TEXT PRIMARY KEY, plan_key TEXT UNIQUE NOT NULL, receipt TEXT NOT NULL)')


def registered(con,state):
    registration=state.get('registration') or {}
    if (state['stage']!='plan_approved' or state['author_blocked'] is not True
            or registration.get('stage')!='complete'):
        raise ValueError('verified scope registration with author blocked required')
    row=con.execute('SELECT receipt FROM product_scope_bases WHERE plan_key=?',(state['key'],)).fetchone()
    receipt=registration['receipt']
    if (not row or json.loads(row[0])!=receipt or receipt['plan_key']!=state['key']
            or receipt['write_grant_issued'] is not False or receipt['delivery_approval'] is not False):
        raise ValueError('immutable non-authorizing scope registry required')
    job.validate_receipt(state,state['materialization']['base'],state['materialization']['receipt'])
    if any(receipt[k]!=state['materialization']['receipt'][k] for k in
           ('contract','contract_sha256','manifest_sha256','frozen_test_sha256','base_sha')):
        raise ValueError('registered scope materialization changed')
    return receipt


def bind(b,key,task_id,effects=None):
    fx=effects or execution.NativeEffects(b)
    with b.LOCK,b.db() as con:
        state=ledger.load(con,key)
        receipt=registered(con,state)
    job.reauthenticate(state,fx)
    intent=state.get('dispatch',{}).get('author',{})
    task=fx.task(task_id,state['context']['author'])
    if (not intent.get('wakeup_id') or intent.get('task_id')!=task_id
            or task.get('id')!=task_id or task.get('wakeup_id')!=intent['wakeup_id']
            or task.get('agent_id')!=state['context']['author']
            or task.get('issue_id')!=state['context']['issue_id'] or task.get('status')!='running'
            or task_id in (state['context']['source_task'],state['proposal_task']['id'],state['review_task']['id'])):
        raise ValueError('exact new running author task and persisted dispatch required')
    binding=dict(receipt,operation='bound_product_scope_base_v1',task_id=task_id,
                 author=state['context']['author'],wakeup_id=intent['wakeup_id'])
    with b.LOCK,b.db() as con:
        initialize(con)
        if ledger.load(con,key)!=state or registered(con,state)!=receipt:
            raise ValueError('scope registration changed during native observation')
        prior=con.execute('SELECT receipt FROM product_scope_task_bases WHERE task_id=? OR plan_key=?',
                          (task_id,key)).fetchone()
        if prior:
            if json.loads(prior[0])!=binding:raise ValueError('scope base already bound to another task')
            return binding
        for table in ('grants','task_contracts'):
            if con.execute('SELECT 1 FROM sqlite_master WHERE name=?',(table,)).fetchone():
                if con.execute('SELECT 1 FROM '+table+' WHERE task_id=?',(task_id,)).fetchone():
                    raise ValueError('task already started or has a historical contract binding')
        con.execute('INSERT INTO product_scope_task_bases VALUES (?,?,?)',(task_id,key,ledger.encoded(binding)))
    return binding


def lookup(b,issue_id,task_id):
    """Return only the explicitly selected base; never choose the latest plan."""
    with b.db() as con:
        if not con.execute("SELECT 1 FROM sqlite_master WHERE name='product_scope_task_bases'").fetchone():return None
        row=con.execute('SELECT receipt,plan_key FROM product_scope_task_bases WHERE task_id=?',(task_id,)).fetchone()
        if not row:return None
        binding=json.loads(row[0]);state=ledger.load(con,row[1]);receipt=registered(con,state)
    if (binding['task_id']!=task_id or binding['issue_id']!=issue_id
            or binding['author']!=state['context']['author']
            or any(binding[k]!=v for k,v in receipt.items() if k!='operation')):
        raise ValueError('task-specific registered base identity changed')
    volume=b.docker('GET','/volumes/'+binding['volume'])
    if (not volume or volume.get('Name')!=binding['volume'] or volume.get('Labels')!=
            {'delivery-kit.owner':b.OWNER,'delivery-kit.scope-plan':state['key']}):
        raise ValueError('task-specific scope volume ownership changed')
    return binding
