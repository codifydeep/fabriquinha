"""Bounded isolated trial launcher, no live dispatch or Docker access."""
import json,os,subprocess,sys
from pathlib import Path
from hermes_cli import kanban_db as kb

board=Path(os.environ['HERMES_KANBAN_DB']).parent
data=json.loads((board/'product-adapter.json').read_text());task_id=next(iter(data['cards']))
if len(data['cards'])!=1:raise ValueError('single-card trial required')
db=kb.connect(board/'kanban.db')
row=kb.get_task(db,task_id)
if row.status=='blocked':kb.unblock_task(db,task_id)
for index in range(int(os.environ.get('PRODUCT_TRIAL_MAX_PHASES','4'))):
    row=kb.get_task(db,task_id)
    if row.status=='done':break
    if row.status=='ready':task=kb.claim_task(db,task_id,claimer='isolated-trial-launcher')
    elif row.status=='review':task=kb.claim_review_task(db,task_id,claimer='isolated-trial-launcher')
    else:raise RuntimeError('trial paused in '+row.status)
    if not task:raise RuntimeError('claim refused')
    env=dict(os.environ,HERMES_PROFILE=task.assignee,HERMES_HOME='/trial-profiles/profiles/'+task.assignee,
             HERMES_KANBAN_TASK=task_id,HERMES_KANBAN_RUN_ID=str(task.current_run_id),HERMES_KANBAN_CLAIM_LOCK=task.claim_lock,
             HERMES_SESSION_SOURCE='kanban',HERMES_KANBAN_WORKSPACE='/trial-work',TERMINAL_CWD='/trial-work',HERMES_WRITE_SAFE_ROOT='/trial-work')
    log=Path('/trial-profiles')/f'{data["attempt"]}-run-{task.current_run_id}.log'
    print(json.dumps(dict(event='worker_started',task=task_id,run=task.current_run_id,profile=task.assignee)),flush=True)
    with log.open('wb') as output:
        try:
            result=subprocess.run([sys.executable,'-m','hermes_cli.main','-p',task.assignee,'--cli','--toolsets','kanban','chat','-q',
                'Complete the assigned isolated adapter task using the scoped instructions and real tools. Start with product_status.'],
                env=env,cwd='/trial-work',stdout=output,stderr=subprocess.STDOUT,timeout=900)
        except subprocess.TimeoutExpired:
            kb.block_task(db,task_id,reason='Isolated worker timed out; technical diagnosis required',kind='capability',expected_run_id=task.current_run_id)
            raise
    row=kb.get_task(db,task_id)
    print(json.dumps(dict(event='worker_exited',run=task.current_run_id,returncode=result.returncode,status=row.status)),flush=True)
    if row.status=='running':
        kb.block_task(db,task_id,reason='Worker exited without durable terminal operation; technical diagnosis required',kind='capability',expected_run_id=task.current_run_id)
        break
print(json.dumps(dict(event='trial_stopped',task=task_id,status=kb.get_task(db,task_id).status,release_homologated=False)),flush=True)
