"""Actual patched stop guard: handoffs, failures, revocation and timeout provenance."""
import json
import os
from pathlib import Path
import tempfile
from unittest.mock import patch
from hermes_cli import kanban_db as kb
from agent.kanban_stop import build_kanban_stop_nudge
from review_block_event import review_block_event
from persistent_stop import closed_execution_message

with tempfile.TemporaryDirectory() as tmp:
    path=Path(tmp)/'kanban.db'; kb.init_db(path); db=kb.connect(path)
    task=kb.create_task(db,title='fixture',assignee='backend_data',initial_status='blocked')
    kb.unblock_task(db,task); author=kb.claim_task(db,task,claimer='author')
    def env(run):
        return patch.dict(os.environ,dict(HERMES_KANBAN_TASK=task,HERMES_KANBAN_DB=str(path),
            HERMES_KANBAN_RUN_ID=str(run.current_run_id),HERMES_KANBAN_CLAIM_LOCK=run.claim_lock))
    with env(author):
        assert closed_execution_message() is None
        failed=[dict(role='tool',name='kanban_complete',content='{"ok":false}')]
        assert build_kanban_stop_nudge(messages=failed)
        assert kb.request_review(db,task,reviewer='techlead',expected_run_id=author.current_run_id)
        assert build_kanban_stop_nudge() is None
        assert 'review_requested' in closed_execution_message()
    reviewer=kb.claim_review_task(db,task,claimer='reviewer')
    with env(author):
        assert build_kanban_stop_nudge() is None
        assert 'review_requested' in closed_execution_message()
    with env(reviewer):
        assert closed_execution_message() is None
        assert 'review_validate' in build_kanban_stop_nudge()
        with patch.dict(os.environ,HERMES_KANBAN_CLAIM_LOCK='wrong'):
            assert closed_execution_message() is None
            assert 'could not be verified' in build_kanban_stop_nudge()
        with patch.dict(os.environ,HERMES_KANBAN_DB=str(Path(tmp)/'missing')):
            assert 'could not be verified' in build_kanban_stop_nudge()
    # Same persisted shape as native deadline exhaustion, including gave_up
    # having no run_id; recovery must derive the exact preceding timed-out run.
    db.execute("UPDATE tasks SET status='blocked',current_run_id=NULL,claim_lock=NULL WHERE id=?",(task,))
    db.execute("UPDATE task_runs SET ended_at=1,outcome='timed_out',claim_lock=NULL WHERE id=?",(reviewer.current_run_id,))
    def event(kind,payload,run=None):
        return db.execute('INSERT INTO task_events(task_id,run_id,kind,payload,created_at) VALUES(?,?,?,?,1)',(task,run,kind,json.dumps(payload)))
    event('timed_out',dict(retry_status='review',pid=123),reviewer.current_run_id)
    event('gave_up',dict(trigger_outcome='timed_out',retry_status='review',pid=123))
    db.commit()
    assert review_block_event(db,task)['kind']=='gave_up'
    with env(reviewer): assert build_kanban_stop_nudge() is None
    event('gave_up',dict(trigger_outcome='timed_out',retry_status='ready',pid=123)); db.commit()
    assert review_block_event(db,task) is None
    event('gave_up',dict(trigger_outcome='timed_out',retry_status='review',pid=999)); db.commit()
    assert review_block_event(db,task) is None
    event('gave_up',dict(trigger_outcome='timed_out',retry_status='review',pid=123)); db.commit()
    assert review_block_event(db,task)
    event('claimed',dict(source_status='review'),reviewer.current_run_id+1); db.commit()
    assert review_block_event(db,task) is None
    event('blocked',dict(reason='[DECISION:ceo] business')); db.commit()
    assert review_block_event(db,task) is None
    db.close()
# Execute the actual injected loop prefix: no next model call after closure.
import ast
source=Path('/opt/hermes/agent/conversation_loop.py').read_text()
tree=ast.parse(source)
loop=next(n for n in ast.walk(tree) if isinstance(n,ast.While) and any(isinstance(v,ast.Name) and v.id=='api_call_count' for v in ast.walk(n.test)))
prefix=ast.Module(body=loop.body[:3],type_ignores=[])
# A break requires a loop scope; append a sentinel representing provider work.
wrapper=ast.Module(body=[ast.While(test=ast.Constant(True),body=prefix.body+[ast.Raise(exc=ast.Call(func=ast.Name(id='AssertionError',ctx=ast.Load()),args=[ast.Constant('provider called after handoff')],keywords=[]),cause=None)],orelse=[])],type_ignores=[])
with patch('persistent_stop.closed_execution_message',return_value='verified closed'):
    scope={}; exec(compile(ast.fix_missing_locations(wrapper),'<native-loop-boundary>','exec'),scope)
    assert scope['_turn_exit_reason']=='kanban_execution_closed'
print('native persistent stop and review timeout provenance: OK')
