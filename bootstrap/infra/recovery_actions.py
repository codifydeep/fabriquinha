"""Audited, fail-closed retraction of premature worktree completion.

Run under the Hermes interpreter during maintenance. Never mark work done.
"""
import argparse
import json
import time

def reopen_delivery(conn, task_id, reason, *, verify_delivery):
    row = conn.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone()
    if not row or row['status'] != 'done' or row['workspace_kind'] != 'worktree':
        raise ValueError('only prematurely completed worktree deliveries can be reopened')
    error = verify_delivery(conn, task_id)
    if not error:
        raise ValueError('delivery is valid; refusal to reopen integrated work')
    event = conn.execute("SELECT payload FROM task_events WHERE task_id=? AND kind='review_requested' ORDER BY id DESC LIMIT 1", (task_id,)).fetchone()
    if not event:
        raise ValueError('missing implementer provenance')
    handoff = json.loads(event['payload'])
    from review_policy import validate_review
    if validate_review(handoff.get('implementer'), handoff.get('reviewer')):
        raise ValueError('review provenance does not match matrix')
    from hermes_cli import kanban_db as kb
    with kb.write_txn(conn):
        live = conn.execute("SELECT 1 FROM task_runs WHERE task_id=? AND status='running'", (task_id,)).fetchone()
        if live:
            raise ValueError('live run exists; refuse to change claim')
        status = kb._landing_status_after_parents(conn, task_id)
        result = conn.execute("UPDATE tasks SET status=?, assignee=?, completed_at=NULL WHERE id=? AND status='done' AND current_run_id IS NULL",
                              (status, handoff['implementer'], task_id))
        if result.rowcount != 1:
            raise ValueError('task changed concurrently; refusing recovery')
        kb._append_event(conn, task_id, 'delivery_reopened', {'reason':reason, 'failed_evidence':error,
            'implementer':handoff['implementer'], 'prior_completed_at':row['completed_at'], 'status':status})
    return status

if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('task')
    parser.add_argument('--reason', required=True)
    args=parser.parse_args()
    from hermes_cli import kanban_db as kb
    from delivery_gate import check_delivery
    from pathlib import Path
    db=Path('/opt/data/kanban/boards/truco-online/kanban.db')
    if not db.with_name('MAINTENANCE').exists():
        raise SystemExit('operator retraction requires active maintenance fence')
    conn=kb.connect(db)
    try:
        print(reopen_delivery(conn,args.task,args.reason,verify_delivery=check_delivery))
    finally:
        conn.close()
