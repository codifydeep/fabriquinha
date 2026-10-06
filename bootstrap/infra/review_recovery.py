"""Narrow native transition following a private-controller recovery receipt."""
import json
import os
import sqlite3
from contextlib import closing


def apply_resume(receipt):
    from hermes_cli import kanban_db as kb
    from review_boundary import worker_state
    state=worker_state()
    if not state or state['mode']!='diagnosis' or state['task']!=receipt['requester'] or state['run']!=receipt['requester_run']:
        raise PermissionError('recovery receipt does not belong to this diagnosis')
    with closing(sqlite3.connect(os.environ['HERMES_KANBAN_DB'])) as db:
        db.row_factory=sqlite3.Row
        with kb.write_txn(db):
            events=db.execute("SELECT payload FROM task_events WHERE task_id=? AND kind='review_recovered'",(receipt['task'],)).fetchall()
            duplicate=any(json.loads(e['payload'])['key']==receipt['key'] for e in events)
            if not duplicate:
                source=db.execute('SELECT * FROM tasks WHERE id=?',(receipt['task'],)).fetchone()
                from review_block_event import review_block_event
                from planning_author_recovery import author_block_event
                author_mode=receipt.get('scope')=='planning_author_only'
                block=(author_block_event if author_mode else review_block_event)(db,receipt['task'])
                publication=receipt.get('scope')=='publication_review_only'
                triage=bool(publication and receipt.get('publication_preflight_fingerprint') and block
                    and block['kind']=='block_loop_detected' and json.loads(block['payload'] or '{}').get('source_status')=='review')
                if not source or (source['status']!='blocked' and not (source['status']=='triage' and triage)) or source['current_run_id'] or source['claim_lock']:
                    raise PermissionError('source no longer safely blocked')
                if source['assignee']!=receipt['reviewer'] or not block or block['id']!=receipt['block_event'] or '[DECISION:' in (block['payload'] or ''):
                    raise PermissionError('stale or human-scoped block')
                if kb._landing_status_after_parents(db,receipt['task'])!='ready':
                    raise PermissionError('dependencies not complete')
                db.execute("UPDATE tasks SET status=?,consecutive_failures=0,last_failure_error=NULL WHERE id=?",('ready' if author_mode else 'review',receipt['task']))
                kb._append_event(db,receipt['task'],'review_recovered',receipt)
        # Parking is not incident resolution. A retry after the committed source
        # transition reuses the same receipt and only completes this final step.
        if not kb.schedule_task(db,state['task'],expected_run_id=state['run'],
            reason='Execution resumed; awaiting verified delivery, not resolved: '+receipt['task']):
            raise ValueError('source resumed but diagnosis could not be parked')
    return dict(resumed=True,task=receipt['task'],revision=receipt['revision'],mode='author' if receipt.get('scope')=='planning_author_only' else 'review',incident_resolved=False)
