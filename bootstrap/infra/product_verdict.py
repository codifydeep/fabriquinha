"""Controller-only durable verdict delivery; native APIs retain their gates."""
import json
from product_workspace import digest


def deliver_verdict(controller, native, envelope):
    from hermes_cli import kanban_db as kb
    key=tuple(envelope[k] for k in ('attempt','task','review_run'))
    row=controller.db.execute('SELECT envelope FROM product_verdicts WHERE attempt=? AND task=? AND review_run=?',key).fetchone()
    if not row or json.loads(row[0])!=envelope:raise PermissionError('private verdict required')
    board=controller.w.claim.board
    if (board/'MAINTENANCE').exists() or (board/'READ_ONLY').exists():raise PermissionError('board fenced')
    marker='product-verdict:'+digest(envelope)
    summary=marker+'\n'+envelope['reason']
    outcome='completed' if envelope['decision']=='approve' else 'changes_requested'
    run=native.execute('SELECT outcome,summary FROM task_runs WHERE id=? AND task_id=?',(key[2],key[1])).fetchone()
    recovered=bool(run and run['outcome']==outcome and run['summary']==summary)
    if not recovered:
        task=native.execute('SELECT claim_lock FROM tasks WHERE id=?',(key[1],)).fetchone()
        request=dict(attempt=key[0],task=key[1],run=key[2],claim=task['claim_lock'] if task else None,
                     revision=envelope['revision'],decision=envelope['decision'],reason=envelope['reason'])
        if controller.verdict(request)!=envelope:raise PermissionError('verdict changed')
        if envelope['decision']=='approve':
            ok=kb.complete_task(native,key[1],expected_run_id=key[2],result=summary,summary=summary,
                                metadata={'product_verdict':envelope},fire_lifecycle_hook=False)
        else:
            ok,detail=kb.request_changes(native,key[1],expected_run_id=key[2],reason=summary)
            if ok and detail!=envelope['author']:raise PermissionError('native author provenance mismatch')
        if not ok:raise PermissionError('native verdict transition refused')
    with controller.db:
        controller.db.execute("UPDATE product_verdicts SET state='DELIVERED' WHERE attempt=? AND task=? AND review_run=?",key)
    return dict(state='DELIVERED',decision=envelope['decision'],revision=envelope['revision'],recovered=recovered,release_homologated=False)
