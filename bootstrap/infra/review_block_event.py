"""Shared selection of the latest recoverable review blocking occurrence."""
import json


def review_block_event(db, task):
    event = db.execute("SELECT * FROM task_events WHERE task_id=? AND kind IN ('blocked','block_loop_detected','gave_up') ORDER BY id DESC LIMIT 1", (task,)).fetchone()
    if not event or '[DECISION:' in (event['payload'] or ''):
        return None
    handoff = db.execute("SELECT id FROM task_events WHERE task_id=? AND kind='review_requested' ORDER BY id DESC LIMIT 1", (task,)).fetchone()
    if not handoff or event['id'] <= handoff['id']:
        return None
    if event['kind'] != 'gave_up':
        return event
    try:
        payload = json.loads(event['payload'] or '{}')
        outcome = payload.get('trigger_outcome')
        if outcome not in ('timed_out', 'crashed') or payload.get('retry_status') != 'review':
            return None
        timeout = db.execute("SELECT * FROM task_events WHERE task_id=? AND id<? AND kind=? ORDER BY id DESC LIMIT 1", (task, event['id'], outcome)).fetchone()
        if not timeout or timeout['id'] <= handoff['id']:
            return None
        claimed = db.execute("SELECT payload FROM task_events WHERE task_id=? AND run_id=? AND kind='claimed' ORDER BY id DESC LIMIT 1", (task, timeout['run_id'])).fetchone()
        run = db.execute('SELECT * FROM task_runs WHERE id=? AND task_id=?', (timeout['run_id'], task)).fetchone()
        detail = json.loads(timeout['payload'] or '{}')
        if (not claimed or not run or not run['ended_at'] or run['outcome'] != outcome
                or json.loads(claimed['payload']).get('source_status') != 'review'
                or detail.get('retry_status') != 'review' or detail.get('pid') != payload.get('pid')):
            return None
        newer = db.execute("SELECT 1 FROM task_events WHERE task_id=? AND id>? AND kind IN ('claimed','review_recovered','review_requested') LIMIT 1", (task, timeout['id'])).fetchone()
        return None if newer else event
    except (ValueError, TypeError, KeyError):
        return None
