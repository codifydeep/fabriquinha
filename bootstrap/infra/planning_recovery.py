"""Bounded recovery of registered planning reviews, authorized by incident ledger."""
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import uuid
from contextlib import closing

PROFILE_ROOT = Path('/opt/data/profiles')


def source(conn, task, config):
    ledger = config.get('coordination_db')
    if not ledger: return None
    row = conn.execute('SELECT * FROM tasks WHERE id=?', (task,)).fetchone()
    if not row: return None
    match = re.match(r'^(INCIDENT|SPIKE)-(t_[a-z0-9]+)(?:\s|$)', row['title'])
    if not match or match[2] not in config['cards'] or row['assignee'] not in ('techlead', 'cto'): return None
    with closing(sqlite3.connect(Path(ledger).resolve().as_uri() + '?mode=ro', uri=True)) as db:
        records = db.execute("SELECT id,data FROM records WHERE attempt=? AND kind='incident'", (config['attempt'],)).fetchall()
    for key, raw in records:
        record = json.loads(raw)
        if record['task'] != match[2] or record['status'] in ('resolved', 'superseded'): continue
        field = 'spike' if match[1] == 'SPIKE' else 'native_task'
        if record.get(field) != task: continue
        if field == 'native_task' and record.get('stage') == 'spike': continue
        if row['assignee'] != record['owner']: continue
        return dict(source=match[2], incident=key, owner=record['owner'])
    return None


def instructions(task, registration):
    return (f'PLANNING TECHNICAL RECOVERY {task}, source {registration["source"]}. '
        'Call review_diagnose. It verifies either an author checkpoint or a frozen review, the exact failure, dependencies '
        'and installed reviewer-skill preflight. If can_resume=true, call review_resume '
        'with the exact revision and block_event. This parks the incident pending actual '
        'independent approval, not success. Author-mode recovery resumes the original author, never submits or approves their draft. Do not complete the incident. '
        'If can_resume=false, comment concrete diagnosis and block(kind="capability"). '
        'No terminal, file edits, model change or CEO technical question. Stop after handoff.')


def handle(planning, task, request):
    from review_board_read import board_read
    from review_block_event import review_block_event
    c = planning.c; op = request['operation']
    if op not in ('diagnose', 'resume'): raise PermissionError('diagnosis/resume only')
    with board_read(c.board / 'kanban.db') as db:
        db.row_factory = sqlite3.Row
        registration = source(db, task['id'], planning.data)
        if not registration: raise PermissionError('unregistered or superseded technical incident')
        tid = registration['source']; original = dict(db.execute('SELECT * FROM tasks WHERE id=?', (tid,)).fetchone())
        card=planning.data['cards'][tid]
        if original['assignee']==card['author'] and card.get('author_recovery_policy'):
            from planning_author_recovery import handle as recover_author
            return recover_author(planning,task,request,db,original)
        block = review_block_event(db, tid)
        try: delivery = c.latest(tid)
        except ValueError:
            return dict(can_resume=False, category='missing_delivery', next_action='technical_operator_diagnosis', ceo_required=False)
        revision = delivery['revision']
        c.store.load(c.attempt, tid, revision)
        planning.inputs(planning.data['cards'][tid])
        preflight_path = c.store.root / 'planning-preflight.json'
        preflight = json.loads(preflight_path.read_text()) if preflight_path.exists() else {}
        reviewer = delivery['reviewer']
        proof = preflight.get('profiles', {}).get(reviewer, {})
        config_file = PROFILE_ROOT / reviewer / 'config.yaml'
        ready = bool(proof.get('loaded') == ['sdlc-review'] and not proof.get('missing')
            and preflight.get('attempt') == c.attempt and config_file.exists()
            and proof.get('config_sha256') == hashlib.sha256(config_file.read_bytes()).hexdigest())
        count = c.db.execute('SELECT count(*) FROM resumptions WHERE task=? AND revision=?', (tid, revision)).fetchone()[0]
        publication=bool(card.get('integration_action'))
        triage=bool(publication and block and block['kind']=='block_loop_detected'
            and json.loads(block['payload'] or '{}').get('source_status')=='review')
        authorization=planning.data.get('publication_policy_repair',{})
        extra=bool(publication and block and authorization.get('task')==tid and authorization.get('block_event')==block['id'] and count==2)
        safe = bool(ready and block and (original['status'] == 'blocked' or (original['status']=='triage' and triage)) and not original['current_run_id']
            and not original['claim_lock'] and original['assignee'] == reviewer and (count < 2 or extra))
        payload=json.loads(block['payload'] or '{}') if block else {}
        last_error=original.get('last_failure_error') or payload.get('reason') or payload.get('error')
        recovery=None
        if publication:
            from publication_access import preflight as access_preflight,recovery_evidence
            access=access_preflight(c,tid)
            recovery=recovery_evidence(c.db,tid,last_error,block,access)
            safe=bool(safe and recovery['can_retry'])
            if extra: safe=bool(safe and recovery['category']=='publication_policy_conflict')
        if op == 'diagnose':
            return dict(task=tid, revision=revision, block_event=block['id'] if block else None,
                can_resume=safe, category=recovery['category'] if recovery else 'review_initialization_or_execution_failure',
                reviewer=reviewer, skill_preflight=ready, immutable_snapshot_verified=True,
                last_error=recovery['last_error'] if recovery else last_error, publication_recovery=recovery, recovery_count=count,
                next_action='review_resume' if safe else 'record_technical_block', ceo_required=False)
        event = int(request['block_event'])
        previous = c.db.execute('SELECT receipt FROM resumptions WHERE task=? AND revision=? AND block_event=?', (tid, request['revision'], event)).fetchone()
        if previous:
            receipt = json.loads(previous['receipt'])
            if receipt['requester'] != task['id'] or receipt['requester_run'] != request['run']:
                raise PermissionError('recovery owned by another execution')
            return receipt
        if not safe or request['revision'] != revision or event != block['id']:
            raise PermissionError('unsafe or obsolete planning recovery')
        receipt = dict(task=tid, revision=revision, block_event=event, reviewer=reviewer,
            requester=task['id'], requester_run=request['run'], key=uuid.uuid4().hex,
            skill_config_sha256=proof['config_sha256'], scope='planning_review_only')
        if recovery:
            receipt.update(scope='publication_review_only',publication_preflight_fingerprint=recovery['preflight_fingerprint'])
        c.db.execute('INSERT INTO resumptions VALUES(?,?,?,?)', (tid, revision, event, json.dumps(receipt)))
        c.db.commit()
        return receipt
