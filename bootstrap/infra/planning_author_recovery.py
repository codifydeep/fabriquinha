"""Evidence-bound author recovery; no submission or approval on the author's behalf."""
import json
import uuid
from planning_drafts import digest


def author_block_event(db,task):
    event=db.execute("SELECT * FROM task_events WHERE task_id=? AND kind IN ('gave_up','blocked','block_loop_detected') ORDER BY id DESC LIMIT 1",(task,)).fetchone()
    if not event or '[DECISION:' in (event['payload'] or ''): return None
    payload=json.loads(event['payload'] or '{}')
    if event['kind']!='gave_up': return None
    if payload.get('trigger_outcome') not in ('timed_out','crashed') or payload.get('retry_status')!='ready': return None
    failed=db.execute('SELECT * FROM task_runs WHERE task_id=? ORDER BY id DESC LIMIT 1',(task,)).fetchone()
    if not failed or not failed['ended_at'] or failed['outcome']!=payload['trigger_outcome']: return None
    claim=db.execute("SELECT payload FROM task_events WHERE task_id=? AND run_id=? AND kind='claimed' ORDER BY id DESC LIMIT 1",(task,failed['id'])).fetchone()
    if not claim or json.loads(claim['payload'] or '{}').get('source_status')=='review': return None
    outcome=db.execute('SELECT payload FROM task_events WHERE task_id=? AND run_id=? AND kind=? ORDER BY id DESC LIMIT 1',
                       (task,failed['id'],payload['trigger_outcome'])).fetchone()
    if not outcome or json.loads(outcome['payload'] or '{}').get('pid')!=payload.get('pid'): return None
    newer=db.execute("SELECT 1 FROM task_events WHERE task_id=? AND id>? AND kind IN ('claimed','review_requested','review_recovered')",(task,event['id'])).fetchone()
    return None if newer else event


def handle(planning,task,request,db,original):
    c=planning.c; tid=original['id']; card=planning.data['cards'][tid]
    block=author_block_event(db,tid)
    draft=c.db.execute('SELECT * FROM planning_drafts WHERE task=?',(tid,)).fetchone()
    if not draft: return dict(can_resume=False,category='missing_author_checkpoint',ceo_required=False,next_action='record_technical_block')
    sha=digest(draft['content']); policy=card.get('author_recovery_policy')
    total=c.db.execute('SELECT receipt FROM resumptions WHERE task=?',(tid,)).fetchall()
    receipts=[json.loads(r[0]) for r in total if json.loads(r[0]).get('scope')=='planning_author_only']
    repeated=any(r['revision']==sha and r.get('policy')==policy for r in receipts)
    last=db.execute('SELECT id FROM task_runs WHERE task_id=? ORDER BY id DESC LIMIT 1',(tid,)).fetchone()
    planning.inputs(card)
    safe=bool(policy=='checkpoint-v1' and block and original['status']=='blocked' and not original['current_run_id']
              and not original['claim_lock'] and original['assignee']==card['author'] and last and draft['run']==last['id']
              and not repeated and len(receipts)<2)
    if request['operation']=='diagnose':
        return dict(task=tid,category='author_checkpoint_available',can_resume=safe,revision=sha,
            block_event=block['id'] if block else None,draft_run=draft['run'],draft_bytes=len(draft['content'].encode()),
            mode='author',policy=policy,next_action='review_resume' if safe else 'record_technical_block',
            ceo_required=False,mitigation='CAS draft patch/adoption; three save budget; registered document language; precise validators')
    previous=c.db.execute('SELECT receipt FROM resumptions WHERE task=? AND revision=? AND block_event=?',
                          (tid,request['revision'],request['block_event'])).fetchone()
    if previous:
        receipt=json.loads(previous[0])
        if (receipt['requester'],receipt['requester_run'])!=(task['id'],request['run']): raise PermissionError('recovery receipt belongs to another run')
        return receipt
    if not safe or request['revision']!=sha or request['block_event']!=block['id']:
        raise PermissionError('unsafe or stale author recovery; no identical retry without new evidence')
    receipt=dict(task=tid,revision=sha,block_event=block['id'],reviewer=card['author'],draft_run=draft['run'],
        requester=task['id'],requester_run=request['run'],key=uuid.uuid4().hex,scope='planning_author_only',policy=policy)
    c.db.execute('INSERT INTO resumptions VALUES(?,?,?,?)',(tid,sha,block['id'],json.dumps(receipt))); c.db.commit()
    return receipt
