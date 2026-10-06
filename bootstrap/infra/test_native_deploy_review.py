"""Native registered no-argument reviewer tool; external HTTP mocked here."""
import json
import os
from pathlib import Path
import tempfile
from unittest.mock import patch
from hermes_cli import kanban_db as kb
from review_controller import Controller
from e2e_controller import ATTEMPT
import review_boundary
with tempfile.TemporaryDirectory() as tmp:
    board=Path(tmp)/ATTEMPT; board.mkdir(); kb.init_db(board/'kanban.db'); db=kb.connect(board/'kanban.db')
    task=kb.create_task(db,title='DEPLOY',assignee='devops',initial_status='blocked')
    config=dict(attempt=ATTEMPT,cards=dict(build='t_build',deploy=task,qa='t_qa'))
    (board/'e2e.json').write_text(json.dumps(config))
    private=Path(tmp)/'private'; private.mkdir(); (private/'e2e-config.json').write_text(json.dumps(config))
    c=Controller(board,private,ATTEMPT,'unused','unused')
    c.e2e.put('published',dict(revision='historical',merge_sha='a'*40))
    db.execute("UPDATE tasks SET status='review',assignee='quality_security' WHERE id=?",(task,)); db.commit()
    run=kb.claim_review_task(db,task,claimer='test')
    env=dict(HERMES_KANBAN_DB=str(board/'kanban.db'),HERMES_KANBAN_TASK=task,HERMES_KANBAN_RUN_ID=str(run.current_run_id),HERMES_KANBAN_CLAIM_LOCK=run.claim_lock)
    with patch.dict(os.environ,env),patch.object(review_boundary,'call',lambda op,**args:c.handle(dict(operation=op,task=task,run=run.current_run_id,claim=run.claim_lock,**args))),patch.object(c.e2e,'http',return_value=dict(passed=True,checks=10)):
        import tools.kanban_tools
        from tools.registry import registry
        result=json.loads(registry.dispatch('e2e_review_validate',{}))
        assert result['passed'] and result['revision']=='a'*40
        assert 'e2e_review_validate' in kb.build_worker_context(db,task)
    c.db.close(); db.close()
print('PASS: actual registered no-argument review tool binds current merge commit')
