"""Mandatory code inspection for ordinary controller-test-first deliveries.

Paths are derived from persisted author permissions and frozen-test provenance,
not reviewer text. Scope-revised deliveries retain their stricter dedicated gate.
"""
import json
try:
    from . import product_scope_task_binding as binding, product_scope_execution as execution
    from .product_scope_review import missing
except ImportError:
    import product_scope_task_binding as binding, product_scope_execution as execution
    from product_scope_review import missing
from portable_contract import safe_path, required_files


def paths(b,issue,source):
    if binding.lookup(b,issue,source) is not None:return None
    with b.db() as con:
        if not con.execute("SELECT 1 FROM sqlite_master WHERE name='delivery_routes'").fetchone():return None
        row=con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(issue,)).fetchone()
        if not row:return None
        route=json.loads(row[0])
        if route.get('test_first') is not True:return None
        if route.get('enabled') is not True:raise ValueError('enabled delivery route required')
        sources=con.execute('SELECT agent_id,issue_id FROM native_bindings WHERE task_id=?',(source,)).fetchall()
        if len(sources)!=1 or tuple(sources[0])!=(route['author'],issue):
            raise ValueError('exact ordinary delivery author binding required')
        tdd=con.execute('SELECT receipt FROM delivery_tdd WHERE task_id=?',(source,)).fetchone()
        if not tdd:raise ValueError('controller test-first delivery evidence required')
        receipt=json.loads(tdd[0])
        if (receipt.get('mode')!='controller_test_first' or receipt.get('implementation_task')!=source
                or not receipt.get('test_task') or receipt['test_task']==source
                or set(receipt.get('red',{}).get('test_sha256',{}))!=set(route['test_first_files'])):
            raise ValueError('unchanged controller frozen-test provenance required')
        names=[r[0] for r in con.execute('SELECT path FROM issue_editables WHERE issue_id=?',(issue,))]
        if con.execute("SELECT 1 FROM sqlite_master WHERE name='task_contracts'").fetchone():
            revised=con.execute('SELECT r.body FROM task_contracts t JOIN contract_revisions r '
                'USING(decision_task) WHERE t.task_id=? AND r.issue_id=?',(source,issue)).fetchone()
            if revised:
                contract=json.loads(revised[0]);allowed=required_files(contract)
                names=[n for n in names if n.removeprefix('/workspace/') in allowed]
    if (not 0<len(names)<=32 or any(not isinstance(n,str) or not n.startswith('/workspace/')
            or not safe_path(n.removeprefix('/workspace/')) for n in names)
            or not set(route['test_first_files'])<={n.removeprefix('/workspace/') for n in names}):
        raise ValueError('bounded registered code and frozen test paths required')
    return sorted({'/delivery/'+name.removeprefix('/workspace/') for name in names})


def read_contract(b,request,effects=None):
    with b.db() as con:
        if not con.execute("SELECT 1 FROM sqlite_master WHERE name='delivery_routes'").fetchone():return None
        row=con.execute('SELECT n.issue_id,n.agent_id,n.task_id,g.mode,a.source_task_id,a.volume '
            'FROM native_bindings n JOIN grants g USING(request_id) '
            'JOIN review_assignments a ON a.review_agent_id=n.agent_id WHERE n.request_id=?',(request,)).fetchone()
    if not row or row[3]!='review':return None
    issue,actor,task,_,source,volume=row;required=paths(b,issue,source)
    if required is None:return None
    with b.db() as con:
        route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(issue,)).fetchone()[0])
        snapshot=con.execute('SELECT volume,status FROM snapshots WHERE task_id=?',(source,)).fetchone()
    if actor!=route['reviewer'] or actor==route['author'] or tuple(snapshot or ())!=(volume,'complete'):
        raise ValueError('exact independent immutable delivery assignment required')
    fx=effects or execution.NativeEffects(b)
    for identity,agent,statuses in ((source,route['author'],('completed',)),(task,actor,('running','completed'))):
        native=fx.task(identity,agent)
        if (native.get('id')!=identity or native.get('agent_id')!=agent
                or native.get('issue_id')!=issue or native.get('status') not in statuses):
            raise ValueError('exact native author and reviewer tasks required')
    return required


def require_complete(required,reads):
    absent=missing(required,reads)
    if absent:raise ValueError('complete independent code and frozen test inspection required: '+','.join(absent))
