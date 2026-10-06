"""Fault-injected native author recovery, exact checkpoint and no auto-approval."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from unittest.mock import patch
from hermes_cli import kanban_db as kb
from review_controller import Controller
from planning_flow import SECTIONS
import review_boundary as boundary
from review_recovery import apply_resume

with tempfile.TemporaryDirectory() as temp:
    root=Path(temp);board=root/'board';board.mkdir();private=root/'private';private.mkdir()
    kb.init_db(board/'kanban.db');db=kb.connect(board/'kanban.db')
    tid=kb.create_task(db,title='DOC-DESIGN',assignee='designer',initial_status='blocked')
    incident=kb.create_task(db,title='SPIKE-'+tid+' — recovery',assignee='cto',initial_status='blocked')
    ledger=root/'coordination.db'
    with sqlite3.connect(ledger) as control:
        control.execute('CREATE TABLE records(attempt,kind,id,data)')
        control.execute('INSERT INTO records VALUES(?,?,?,?)',('test','incident','i_one',json.dumps(dict(task=tid,owner='cto',status='open',stage='spike',spike=incident))))
    brief='approved';sha=hashlib.sha256(brief.encode()).hexdigest()
    data=dict(attempt='test',brief_sha256=sha,coordination_db=str(ledger),cards={tid:dict(role='design',author='designer',reviewer='produto',parents=[],objective='Design',author_recovery_policy='checkpoint-v1')})
    for path in (board/'planning.json',private/'planning-config.json'):path.write_text(json.dumps(data))
    (private/'planning-brief.md').write_text(brief)
    c=Controller(board,private,'test','unused','unused')
    def env(task,run):return patch.dict(os.environ,HERMES_KANBAN_DB=str(board/'kanban.db'),HERMES_KANBAN_TASK=task,
        HERMES_KANBAN_RUN_ID=str(run.current_run_id),HERMES_KANBAN_CLAIM_LOCK=run.claim_lock)
    def broker(op,**args):
        s=boundary.worker_state();return c.handle(dict(args,operation=op,task=s['task'],run=s['run'],claim=s['claim']))
    with patch.object(boundary,'call',broker):
        kb.unblock_task(db,tid);author=kb.claim_task(db,tid,claimer='author')
        text=sha+'\n'+'\n'.join('## '+s+'\nConcrete product decisions and acceptance criteria.' for s in SECTIONS)
        with env(tid,author):
            broker('planning_write',content=text)
            kb.block_task(db,tid,kind='capability',reason='fault injected timeout',expected_run_id=author.current_run_id)
        db.execute("UPDATE task_runs SET outcome='timed_out' WHERE id=?",(author.current_run_id,))
        db.execute("INSERT INTO task_events(task_id,run_id,kind,payload,created_at) VALUES(?,?,'timed_out',?,1)",
            (tid,author.current_run_id,json.dumps(dict(retry_status='ready',pid=123))))
        db.execute("INSERT INTO task_events(task_id,kind,payload,created_at) VALUES(?,'gave_up',?,1)",
            (tid,json.dumps(dict(trigger_outcome='timed_out',retry_status='ready',pid=123))))
        db.commit()
        kb.unblock_task(db,incident);diagnosis=kb.claim_task(db,incident,claimer='cto')
        with env(incident,diagnosis):
            result=broker('diagnose');assert result['can_resume'] and result['mode']=='author',result
            assert boundary.intercept('planning_patch',{})['error']=='operation_forbidden'
            try:broker('resume',revision='0'*64,block_event=result['block_event'])
            except PermissionError:pass
            else:raise AssertionError('stale checkpoint accepted')
            receipt=broker('resume',revision=result['revision'],block_event=result['block_event'])
            assert receipt==broker('resume',revision=result['revision'],block_event=result['block_event'])
            restored=apply_resume(receipt);assert restored['mode']=='author' and not restored['incident_resolved']
        assert kb.get_task(db,tid).status=='ready'
        assert kb.get_task(db,incident).status=='scheduled'
        assert not c.db.execute('SELECT 1 FROM approvals WHERE task=?',(tid,)).fetchone()
        assert not c.db.execute('SELECT 1 FROM deliveries WHERE task=?',(tid,)).fetchone()
        resumed=kb.claim_task(db,tid,claimer='resumed-author')
        with env(tid,resumed):
            from tools.registry import registry
            import tools.kanban_tools
            from model_tools import get_tool_definitions
            assert 'planning_patch' in {d['function']['name'] for d in get_tool_definitions(['kanban'],quiet_mode=True)}
            out=json.loads(registry.dispatch('planning_patch',dict(expected_sha=hashlib.sha256(text.encode()).hexdigest(),edits=[])))
            assert out['ready_for_review'],out
            assert kb.request_review(db,tid,reviewer='produto',expected_run_id=resumed.current_run_id)
        assert kb.get_task(db,tid).status=='review'
    db.close();c.db.close()
print('PASS native author recovery: exact failed author/checkpoint, stale rejection, scoped resume, parked incident, actual patch registry, handoff without approval.')
