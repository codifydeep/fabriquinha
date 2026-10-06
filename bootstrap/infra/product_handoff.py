"""Controller-only outbox consumer; never a worker/tool operation."""
import json


def deliver(controller, board_db, envelope):
    from hermes_cli import kanban_db as kb
    key = tuple(envelope[k] for k in ('attempt', 'task', 'run', 'version'))
    stored = controller.db.execute('SELECT envelope FROM product_handoffs WHERE attempt=? AND task=? AND run=? AND version=?', key).fetchone()
    if not stored or json.loads(stored[0]) != envelope:
        raise PermissionError('private outbox envelope required')
    if (controller.w.claim.board / 'MAINTENANCE').exists() or (controller.w.claim.board / 'READ_ONLY').exists():
        raise PermissionError('board fenced')
    marker = dict(revision=envelope['revision'], evidence_sha256=envelope['evidence_sha256'], attempt=envelope['attempt'])
    run = board_db.execute('SELECT outcome,metadata FROM task_runs WHERE id=? AND task_id=?', (envelope['run'], envelope['task'])).fetchone()
    recovered = bool(run and run['outcome'] == 'review_requested' and
                     json.loads(run['metadata'] or '{}').get('product_handoff') == marker)
    if not recovered:
        task = board_db.execute('SELECT claim_lock FROM tasks WHERE id=?', (envelope['task'],)).fetchone()
        request = dict(attempt=envelope['attempt'], task=envelope['task'], run=envelope['run'], claim=task['claim_lock'] if task else None)
        current, row = controller.w.state(request, write=True)
        if row[2] != envelope['version']:
            raise PermissionError('draft changed after submission')
        ok, reason = kb.request_review(board_db, envelope['task'], reviewer=envelope['reviewer'],
                                     expected_run_id=current['run'], with_reason=True,
                                     summary='Immutable product delivery ' + envelope['revision'],
                                     metadata={'product_handoff': marker})
        if not ok:
            raise PermissionError('native handoff refused: ' + str(reason))
    # If this commit fails, the durable native run marker above makes replay safe.
    with controller.db:
        controller.db.execute("UPDATE product_handoffs SET state='DELIVERED' WHERE attempt=? AND task=? AND run=? AND version=?", key)
    return dict(state='DELIVERED', revision=envelope['revision'], recovered=recovered, approved=False)
