"""Native recovery receipt -> review transition; no model calls or product writes."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from unittest.mock import patch
from hermes_cli import kanban_db as kb
from review_controller import Controller
from planning_flow import SECTIONS, claim_allowed
import planning_recovery
import review_boundary as boundary
from review_recovery import apply_resume
publication_case=os.environ.get('PUBLICATION_RECOVERY_NATIVE')=='1'
author_profile='techlead' if publication_case else 'designer'
reviewer_profile='cto' if publication_case else 'produto'

with tempfile.TemporaryDirectory() as temp:
    root=Path(temp); board=root/'board'; board.mkdir(); private=root/'private'; private.mkdir()
    kb.init_db(board/'kanban.db'); db=kb.connect(board/'kanban.db')
    task=kb.create_task(db,title='DOC-DESIGN',assignee=author_profile,initial_status='blocked')
    incident=kb.create_task(db,title='SPIKE-'+task+' — recovery',assignee='cto',initial_status='blocked')
    forged=kb.create_task(db,title='SPIKE-'+task+' — forged',assignee='cto',initial_status='blocked')
    for tid in (task,incident,forged):
        workspace=board/'workspaces'/tid; workspace.mkdir(parents=True)
        db.execute('UPDATE tasks SET workspace_path=? WHERE id=?',(str(workspace),tid))
    db.commit()
    ledger=root/'coordination.db'
    with sqlite3.connect(ledger) as control:
        control.execute('CREATE TABLE records(attempt,kind,id,data)')
        control.execute('INSERT INTO records VALUES(?,?,?,?)',('test','incident','i_one',json.dumps(dict(task=task,owner='cto',status='open',stage='spike',spike=incident,native_task='t_prior'))))
    brief='approved'; sha=hashlib.sha256(brief.encode()).hexdigest()
    data=dict(attempt='test',brief_sha256=sha,coordination_db=str(ledger),cards={task:dict(role='plan' if publication_case else 'design',author=author_profile,reviewer=reviewer_profile,parents=[],objective='Design')})
    if publication_case: data['cards'][task]['integration_action']='merge_foundation'
    for path in (board/'planning.json',private/'planning-config.json'): path.write_text(json.dumps(data))
    (private/'planning-brief.md').write_text(brief)
    profiles=root/'profiles'; (profiles/reviewer_profile).mkdir(parents=True)
    (profiles/reviewer_profile/'config.yaml').write_text('review skill available')
    configsha=hashlib.sha256((profiles/reviewer_profile/'config.yaml').read_bytes()).hexdigest()
    c=Controller(board,private,'test','unused','unused')
    def env(tid,run): return patch.dict(os.environ,HERMES_KANBAN_DB=str(board/'kanban.db'),HERMES_KANBAN_TASK=tid,
        HERMES_KANBAN_RUN_ID=str(run.current_run_id),HERMES_KANBAN_CLAIM_LOCK=run.claim_lock)
    def broker(op,**args):
        state=boundary.worker_state(); return c.handle(dict(args,operation=op,task=state['task'],run=state['run'],claim=state['claim']))
    access=dict(passed=False,fingerprint='failed',files=[])
    with patch.object(boundary,'call',broker),patch.object(planning_recovery,'PROFILE_ROOT',profiles),patch('publication_access.preflight',lambda *_:dict(access)):
        kb.unblock_task(db,task); author=kb.claim_task(db,task,claimer='author')
        with env(task,author):
            broker('planning_write',content=sha+'\n'+'\n'.join('## '+s+'\nConcrete document acceptance and product decisions.' for s in SECTIONS))
            assert kb.request_review(db,task,reviewer=reviewer_profile,expected_run_id=author.current_run_id)
        reviewer=kb.claim_review_task(db,task,claimer='reviewer')
        with env(task,reviewer):
            reason='PermissionError [Errno 13] /opt/data/governance/execution.json' if publication_case else 'review skill unavailable'
            assert kb.block_task(db,task,kind='capability',reason=reason,expected_run_id=reviewer.current_run_id)
        if publication_case:
            db.execute("UPDATE tasks SET status='triage',last_failure_error=NULL WHERE id=?",(task,))
            kb._append_event(db,task,'block_loop_detected',dict(reason=reason,source_status='review'))
            db.commit()
        assert not claim_allowed(db,forged)
        kb.unblock_task(db,incident); diagnosis=kb.claim_task(db,incident,claimer='cto'); assert diagnosis
        with env(incident,diagnosis):
            assert not broker('diagnose')['can_resume']
            (private/'planning-preflight.json').write_text(json.dumps(dict(attempt='test',profiles={reviewer_profile:dict(loaded=['sdlc-review'],missing=[],config_sha256=configsha)})))
            if publication_case:
                denied=broker('diagnose')
                assert not denied['can_resume'] and 'PermissionError' in denied['last_error']
                access.update(passed=True,fingerprint='repaired',files=['/opt/data/governance/execution.json'])
            result=broker('diagnose'); assert result['can_resume']
            assert boundary.intercept('terminal',{})['error']=='operation_forbidden'
            assert boundary.intercept('kanban_complete',{})['error']=='operation_forbidden'
            try: broker('resume',revision='0'*64,block_event=result['block_event'])
            except PermissionError: pass
            else: raise AssertionError('stale recovery accepted')
            receipt=broker('resume',revision=result['revision'],block_event=result['block_event'])
            if publication_case:
                assert receipt['scope']=='publication_review_only' and receipt['publication_preflight_fingerprint']=='repaired'
            assert broker('resume',revision=result['revision'],block_event=result['block_event'])==receipt
            restored=apply_resume(receipt); assert restored['resumed'] and not restored['incident_resolved']
        assert kb.get_task(db,task).status=='review'
        assert kb.get_task(db,incident).status=='scheduled'
        assert not c.db.execute('SELECT 1 FROM approvals WHERE task=?',(task,)).fetchone()
    db.close(); c.db.close()
print('PASS native planning recovery: ledger registration, skill readiness, stale rejection, receipt idempotency, review resume without approval, incident parked.')
