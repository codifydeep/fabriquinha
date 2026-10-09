"""Controller-bound code inspection for scoped deliveries, not model claims.

The same immutable snapshot is inspected again when an earlier review only ran
tests. No source edit, historical receipt rewrite or implicit release approval.
"""
import json
try:
    from . import product_scope_task_binding as binding,product_scope_worker as worker
    from . import product_scope_execution as execution
except ImportError:
    import product_scope_task_binding as binding,product_scope_worker as worker
    import product_scope_execution as execution


def paths(b,issue,source):
    selected=binding.lookup(b,issue,source)
    if selected is None:return None
    configuration=worker.selection(b,issue,source)
    result={'/delivery/'+p.removeprefix('/workspace/') for p in configuration['editable_paths']}
    result.update('/delivery/'+p for p in selected['frozen_test_sha256'])
    if not 0<len(result)<=32:raise ValueError('bounded scoped review inspection required')
    return sorted(result)


def missing(read_paths,reads):
    return [p for p in read_paths if type(reads.get(p,{}).get('lines')) is not int
            or type(reads.get(p,{}).get('total_lines')) is not int
            or reads[p]['lines']<=0 or reads[p]['lines']!=reads[p]['total_lines']]


def read_contract(b,request):
    with b.db() as con:
        if not con.execute("SELECT 1 FROM sqlite_master WHERE name='product_scope_task_bases'").fetchone():return None
        row=con.execute('SELECT n.issue_id,n.agent_id,n.task_id,g.mode,a.source_task_id,a.volume '
            'FROM native_bindings n JOIN grants g USING(request_id) '
            'JOIN review_assignments a ON a.review_agent_id=n.agent_id WHERE n.request_id=?',(request,)).fetchone()
    if not row or row[3]!='review':return None
    issue,actor,task,_,source,volume=row
    required=paths(b,issue,source)
    if required is None:return None
    with b.db() as con:
        route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(issue,)).fetchone()[0])
        snap=con.execute('SELECT volume,status FROM snapshots WHERE task_id=?',(source,)).fetchone()
    if route.get('enabled') is not True or actor!=route['reviewer'] or actor==route['author'] or tuple(snap or ())!=(volume,'complete'):
        raise ValueError('exact scoped review assignment required')
    native=execution.NativeEffects(b).task(task,actor)
    if native.get('issue_id')!=issue or native.get('status') not in ('running','completed'):
        raise ValueError('exact scoped native reviewer required')
    return required


def inspection(b,issue,source,review,effects=None):
    required=paths(b,issue,source)
    if required is None:return None
    with b.db() as con:
        row=con.execute('SELECT source_task_id,reviewer_agent_id,manifest_sha256,status FROM reviews '
                        'WHERE review_task_id=?',(review['review_task_id'],)).fetchone()
        route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(issue,)).fetchone()[0])
        snapshot=con.execute('SELECT volume,status FROM snapshots WHERE task_id=?',(source,)).fetchone()
    if (not row or tuple(row)!=(source,route['reviewer'],review['manifest_sha256'],'approved')
            or review.get('source_task_id')!=source or review.get('reviewer_agent_id')!=route['reviewer']
            or review.get('status')!='approved' or not snapshot or snapshot[1]!='complete'):
        raise ValueError('exact approved snapshot inspection reference required')
    fx=effects or execution.NativeEffects(b)
    task=fx.task(review['review_task_id'],route['reviewer'])
    if task.get('issue_id')!=issue or task.get('status')!='completed':
        raise ValueError('completed independent native inspection required')
    return dict(operation='qualified_scoped_review_inspection_v1',source_task=source,
        review_task=review['review_task_id'],manifest_sha256=review['manifest_sha256'],
        read_paths=required,missing_read_paths=missing(required,fx.delivery_reads(task)),
        delivery_approval=False,author_restarted=False)
