"""Real Hermes handoffs and mode boundaries; external effects stubbed here."""
import json
import os
from pathlib import Path
import tempfile
from unittest.mock import patch
from hermes_cli import kanban_db as kb
from review_controller import Controller
from e2e_controller import ATTEMPT
from e2e_policy import BASELINE,NOTES
import review_boundary as boundary

GOOD='def winner(a, b):\n    return "A" if a >= 12 else "B" if b >= 12 else None\n'
TESTS='import unittest\nfrom app import winner\nclass Cases(unittest.TestCase):\n'+''.join(f'    def test_{i}(self): self.assertEqual(winner({a},{b}),{v!r})\n' for i,(a,b,v) in enumerate([(12,0,'A'),(0,12,'B'),(12,13,'A'),(0,0,None),(11,11,None)]))
with tempfile.TemporaryDirectory() as tmp:
    board=Path(tmp)/ATTEMPT; board.mkdir(); kb.init_db(board/'kanban.db'); db=kb.connect(board/'kanban.db')
    private=Path(tmp)/'private'; private.mkdir()
    build=kb.create_task(db,title='E2E BUILD',assignee='backend_data',initial_status='blocked')
    data=dict(attempt=ATTEMPT,cards=dict(build=build,deploy='t_other',qa='t_qa'))
    (board/'e2e.json').write_text(json.dumps(data)); (private/'e2e-config.json').write_text(json.dumps(data))
    root=board/'workspaces'/build; root.mkdir(parents=True)
    db.execute('UPDATE tasks SET workspace_path=? WHERE id=?',(str(root),build)); db.commit()
    controller=Controller(board,private,ATTEMPT,'unused','unused'); engine=controller.e2e
    def env(run): return patch.dict(os.environ,dict(HERMES_KANBAN_TASK=build,HERMES_KANBAN_DB=str(board/'kanban.db'),HERMES_KANBAN_WORKSPACE=str(root),HERMES_KANBAN_RUN_ID=str(run.current_run_id),HERMES_KANBAN_CLAIM_LOCK=run.claim_lock))
    def broker(operation,**args):
        state=boundary.worker_state()
        return controller.handle(dict(args,operation=operation,task=build,run=state['run'],claim=state['claim']))
    def publish(task,run):
        revision=engine.capture(task,run,engine.files(task))
        return engine.put('published',dict(revision=revision,head='a'*40,base='b'*40,pr=1,author='backend_data',author_run=run,reviewer='techlead',notes=(root/'NOTES.md').exists()))
    kb.unblock_task(db,build)
    with patch.object(boundary,'call',broker),patch.object(engine,'publish',publish):
        author=kb.claim_task(db,build,claimer='author')
        with env(author):
            import tools.kanban_tools
            from tools.registry import registry
            assert 'E2E rehearsal' in kb.build_worker_context(db,build)
            assert boundary.intercept('terminal',{'command':'id'})['error']=='operation_forbidden'
            registry.dispatch('e2e_write',dict(path='app.py',content=BASELINE))
            registry.dispatch('e2e_write',dict(path='test_user.py',content=TESTS))
            with patch.object(engine,'tests',return_value=dict(returncode=1,tests=12,passed=False,output='FAILED (failures=4)')):
                registry.dispatch('e2e_test',dict(stage='red'))
            registry.dispatch('e2e_write',dict(path='app.py',content=GOOD))
            with patch.object(engine,'tests',return_value=dict(returncode=0,tests=12,passed=True,output='OK')):
                registry.dispatch('e2e_test',dict(stage='green'))
            registry.dispatch('e2e_submit',{})
            # Simulate legacy/external drift; recover through the actual registry.
            (root/'NOTES.md').write_text(NOTES)
            restored=json.loads(registry.dispatch('e2e_restore_published',{}))
            assert restored['passed'] and restored['backup_id']
            assert not (root/'NOTES.md').exists()
            assert kb.request_review(db,build,reviewer='techlead',expected_run_id=author.current_run_id)
        reviewer=kb.claim_review_task(db,build,claimer='reviewer')
        with env(reviewer):
            assert boundary.intercept('e2e_write',dict(path='app.py',content=BASELINE))['error']=='operation_forbidden'
            revision=broker('inspect')['delivery']['revision']
            with patch.object(engine,'tests',return_value=dict(passed=True,tests=12)):
                broker('validate',revision=revision)
            assert kb.request_changes(db,build,reason='Missing notes',expected_run_id=reviewer.current_run_id)[0]
        author=kb.claim_task(db,build,claimer='rework')
        with env(author):
            registry.dispatch('e2e_write',dict(path='NOTES.md',content=NOTES.rstrip()))
            assert (root/'NOTES.md').read_text()==NOTES
            registry.dispatch('e2e_submit',{})
            assert kb.request_review(db,build,reviewer='techlead',expected_run_id=author.current_run_id)
        reviewer=kb.claim_review_task(db,build,claimer='reviewer2')
        with env(reviewer):
            fresh=broker('inspect')['delivery']['revision']; assert fresh!=revision
            try: broker('validate',revision=revision)
            except ValueError: pass
            else: raise AssertionError('obsolete revision accepted')
            try: kb.complete_task(db,build,expected_run_id=reviewer.current_run_id,result='not merged',fire_lifecycle_hook=False)
            except ValueError: pass
            else: raise AssertionError('completed without merge')
            with patch.object(engine,'tests',return_value=dict(passed=True,tests=12)):
                broker('validate',revision=fresh)
            # Only the external merge is stubbed; prove native approve binds run.
            approval=dict(approved=True,revision=fresh,author='backend_data',reviewer='techlead',review_run=reviewer.current_run_id)
            published=engine.published(); published.update(merged=True,merge_sha='c'*40,approval=approval); engine.put('published',published)
            assert kb.complete_task(db,build,expected_run_id=reviewer.current_run_id,result='approved',fire_lifecycle_hook=False)
        assert kb.get_task(db,build).status=='done'
    db.close(); controller.db.close()
print('PASS native E2E: bounded tools, TDD, immutable rework, stale review/merge gates, independent completion')
