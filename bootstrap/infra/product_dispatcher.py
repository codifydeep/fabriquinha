"""Two bounded slots, role exclusion and durable eligibility aging. No secrets."""
import fcntl,json,os,signal,sqlite3,subprocess,sys,time
from pathlib import Path
from hermes_cli import kanban_db as kb
from product_scheduler import candidates
from product_lane import emit

def terminate(child):
    if child.poll() is not None:return
    os.killpg(child.pid,signal.SIGTERM)
    try:child.wait(timeout=5)
    except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait()

def launch(board,tid,claimed,card):
    mode='review' if claimed.assignee==card['reviewer'] else 'implementation'
    work=Path('/trial-work')/(tid+'-'+str(claimed.current_run_id));work.mkdir(parents=True,exist_ok=True)
    env=dict(os.environ,HERMES_PROFILE=claimed.assignee,HERMES_HOME='/trial-profiles/profiles/'+claimed.assignee,
        HERMES_KANBAN_TASK=tid,HERMES_KANBAN_RUN_ID=str(claimed.current_run_id),HERMES_KANBAN_CLAIM_LOCK=claimed.claim_lock,
        HERMES_SESSION_SOURCE='kanban',HERMES_KANBAN_WORKSPACE=str(work),TERMINAL_CWD=str(work),HERMES_WRITE_SAFE_ROOT=str(work))
    log=Path('/trial-profiles')/f'lobby-{tid}-run-{claimed.current_run_id}.log';output=log.open('wb')
    prompt=('Execute your technical coordination card. Start with work_context and team_status. Diagnose evidence or independently review the proposal. Use a terminal team operation, never a textual promise.'
        if card.get('scope')=='coordination' else 'Execute your assigned REAL Truco card with scoped tools. Start with work_context and product_status. Follow the registered evidence contract and independent immutable review. Save a checkpoint before the durable handoff, then stop.')
    try:child=subprocess.Popen([sys.executable,'-m','hermes_cli.main','-p',claimed.assignee,'--cli','--toolsets','kanban','chat','-q',prompt],env=env,cwd=work,stdout=output,stderr=subprocess.STDOUT,start_new_session=True)
    except BaseException:output.close();raise
    emit(board,'started',task=tid,run=claimed.current_run_id,profile=claimed.assignee,mode=mode)
    return dict(task=tid,run=claimed.current_run_id,profile=claimed.assignee,mode=mode,child=child,output=output,log=log,started=time.monotonic(),card=card)

def main():
    board=Path(os.environ['HERMES_KANBAN_DB']).parent
    lock=(board/'lane.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    config=json.loads((board/'product-adapter.json').read_text())
    if config.get('scope')!='truco-lobby':raise PermissionError('real product board required')
    db=kb.connect(board/'kanban.db');queue=sqlite3.connect(board/'lane-events.db',timeout=15);prefix='truco-lobby-lane';active={}
    def stop(signum,frame):
        for job in active.values():terminate(job['child']);job['output'].close()
        raise SystemExit(128+signum)
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    for tid in config['cards']:
        task=kb.get_task(db,tid)
        if task.status=='running':
            if task.claim_lock!=prefix:raise PermissionError('foreign worker claim; refuse takeover')
            kb.block_task(db,tid,reason='Dispatcher restarted; controller draft and run log preserved. Diagnose before a new run.',kind='capability',expected_run_id=task.current_run_id)
            emit(board,'blocked',task=tid,owner='techlead',reason='dispatcher_restart',next_action='Inspect saved draft and last worker log; no blind retry')
    while True:
        for tid,job in list(active.items()):
            child=job['child'];code=child.poll()
            if code is None and time.monotonic()-job['started']<1200:continue
            if code is None:terminate(child);code=124
            job['output'].close();current=kb.get_task(db,tid)
            if current.status=='running' and current.current_run_id==job['run']:
                kb.block_task(db,tid,reason='Worker exited without durable handoff; controller draft preserved. Inspect '+job['log'].name,kind='capability',expected_run_id=job['run'])
            current=kb.get_task(db,tid)
            emit(board,'exited',task=tid,run=job['run'],profile=job['profile'],mode=job['mode'],exit_code=code,status=current.status,
                 checkpoint=dict(log=job['log'].name,draft='controller-owned; query product_read',native_run=job['run']),
                 next_action='Independent review' if current.status=='review' else 'Resume author findings' if current.status=='ready' else 'Inspect durable evidence and integration/diagnosis')
            del active[tid]
        if (board/'MAINTENANCE').exists() or (board/'DRAIN').exists():time.sleep(5);continue
        config=json.loads((board/'product-adapter.json').read_text())
        from product_manifest import verify,profile_check
        verify(config);tasks=[]
        for tid,card in list(config['cards'].items()):
            if tid in active:continue
            from product_review_feedback import contain
            if contain(db,tid,card):
                emit(board,'review_escalation',task=tid,profile='cto',next_action='Repeated findings need evidenced diagnosis.');continue
            task=kb.get_task(db,tid)
            if card.get('scope')=='pr_review' and task.status=='ready':
                kb.block_task(db,tid,reason='PR findings need an updated exact-SHA packet before another review.',kind='capability');continue
            tasks.append(dict(task=tid,profile=task.assignee,status=task.status,scope=card.get('scope','product')))
        for item in candidates(queue,tasks,list(active.values()),config.get('dispatch_slots',1),int(time.time())):
            tid=item['task'];card=config['cards'][tid]
            try:profile_check('/trial-profiles',item['profile'])
            except (PermissionError,FileNotFoundError):
                kb.block_task(db,tid,reason='Runtime profile preflight failed; platform owner must restore registered model/budget/configuration.',kind='capability')
                emit(board,'blocked',task=tid,profile='devops',next_action='Repair profile preflight; do not change model implicitly.');continue
            claim=(kb.claim_review_task if item['status']=='review' else kb.claim_task)(db,tid,claimer=prefix,ttl_seconds=1500)
            if not claim:continue
            try:active[tid]=launch(board,tid,claim,card)
            except Exception as exc:
                kb.block_task(db,tid,reason='Worker launch failed: '+type(exc).__name__,kind='capability',expected_run_id=claim.current_run_id)
                emit(board,'blocked',task=tid,profile='devops',next_action='Inspect launch failure and preserved claim.')
        time.sleep(5)
if __name__=='__main__':main()
