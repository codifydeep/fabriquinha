"""Persistent, scoped real-product dispatcher. No Docker, Git or Telegram secrets.

One active worker in this initial lane (below the global ceiling of two). Never
unblocks a failed card automatically; preserves drafts and reports technical owner.
"""
import fcntl,json,os,signal,sqlite3,subprocess,sys,time
from pathlib import Path
from hermes_cli import kanban_db as kb
from product_fairness import ordered,claimed as record_claim

def emit(board,event,**data):
    payload=dict(event=event,at=int(time.time()),**data)
    with sqlite3.connect(board/'lane-events.db') as db:
        db.execute('CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,payload TEXT,sent INTEGER DEFAULT 0)')
        db.execute('INSERT INTO events(payload) VALUES(?)',(json.dumps(payload),))
    print(json.dumps(payload),flush=True)

def main():
    board=Path(os.environ['HERMES_KANBAN_DB']).parent
    lock=(board/'lane.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    config=json.loads((board/'product-adapter.json').read_text())
    if config.get('scope')!='truco-lobby':raise PermissionError('real product board required')
    db=kb.connect(board/'kanban.db');prefix='truco-lobby-lane'
    for tid in config['cards']:
        task=kb.get_task(db,tid)
        if task.status=='running':
            if task.claim_lock!=prefix:raise PermissionError('foreign worker claim; refuse takeover')
            kb.block_task(db,tid,reason='Dispatcher restarted during execution; draft preserved. Tech Lead must diagnose before a new run.',kind='capability',expected_run_id=task.current_run_id)
            emit(board,'blocked',task=tid,owner='techlead',reason='dispatcher_restart',next_action='Inspect saved draft and last worker log; no blind retry')
    last={}
    while True:
        if (board/'MAINTENANCE').exists():time.sleep(5);continue
        config=json.loads((board/'product-adapter.json').read_text())
        for tid,card in ordered(board,config['cards']):
            from product_review_feedback import contain
            if contain(db,tid,card):
                emit(board,'review_escalation',task=tid,profile='cto',next_action='Repeated changes require CTO diagnosis before another implementation run.')
                continue
            task=kb.get_task(db,tid)
            if card.get('scope')=='pr_review' and task.status=='ready':
                kb.block_task(db,tid,reason='PR changes requested: preserve verdict and update exact Git packet before re-review; technical owner Tech Lead.',kind='capability')
                emit(board,'blocked',task=tid,owner='techlead',next_action='Address PR findings and register a new exact-SHA packet; no blind PR re-review')
                continue
            if task.status not in ('ready','review'):
                if last.get(tid)!=task.status:
                    owner='cto' if card['author'] in ('cto','techlead') else 'techlead'
                    descriptions={'done':'Evidence recorded; snapshot approval is not PR integration or homologation.',
                        'archived':'Historical/superseded diagnosis; preserved for audit, not an active impediment.',
                        'scheduled':'Waiting for dependencies/capability; not a worker failure.',
                        'blocked':'Technical owner diagnoses saved evidence; no blind repeated execution.'}
                    emit(board,'status',task=tid,status=task.status,owner=owner,profile=task.assignee,
                         next_action=descriptions.get(task.status,'Inspect durable card state.'))
                    last[tid]=task.status
                continue
            claimed=(kb.claim_review_task if task.status=='review' else kb.claim_task)(db,tid,claimer=prefix,ttl_seconds=1500)
            if not claimed:continue
            record_claim(board,tid)
            mode='review' if task.status=='review' else 'implementation'
            env=dict(os.environ,HERMES_PROFILE=claimed.assignee,HERMES_HOME='/trial-profiles/profiles/'+claimed.assignee,
                HERMES_KANBAN_TASK=tid,HERMES_KANBAN_RUN_ID=str(claimed.current_run_id),HERMES_KANBAN_CLAIM_LOCK=claimed.claim_lock,
                HERMES_SESSION_SOURCE='kanban',HERMES_KANBAN_WORKSPACE='/trial-work',TERMINAL_CWD='/trial-work',HERMES_WRITE_SAFE_ROOT='/trial-work')
            log=Path('/trial-profiles')/f'lobby-{tid}-run-{claimed.current_run_id}.log'
            emit(board,'started',task=tid,run=claimed.current_run_id,profile=claimed.assignee,mode=mode)
            child=None
            def stop(signum,frame):
                if child is not None and child.poll() is None:os.killpg(child.pid,signal.SIGTERM)
                raise SystemExit(128+signum)
            signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
            with log.open('wb') as output:
                child=subprocess.Popen([sys.executable,'-m','hermes_cli.main','-p',claimed.assignee,'--cli','--toolsets','kanban','chat','-q',
                    ('Execute your technical coordination card. Start with team_status. Diagnose evidence or independently review the proposal. Use a terminal team operation, never a textual promise.' if card.get('scope')=='coordination' else 'Execute your assigned REAL Truco lobby card with the scoped tools. Start with product_status. Follow actual TDD and independent immutable review. Stop after the durable handoff.')],
                    env=env,cwd='/trial-work',stdout=output,stderr=subprocess.STDOUT,start_new_session=True)
                try:code=child.wait(timeout=1200)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid,signal.SIGTERM)
                    try:child.wait(timeout=10)
                    except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait()
                    code=124
            current=kb.get_task(db,tid)
            if current.status=='running':
                kb.block_task(db,tid,reason='Worker exited without durable handoff; inspect '+log.name,kind='capability',expected_run_id=claimed.current_run_id)
            current=kb.get_task(db,tid)
            emit(board,'exited',task=tid,run=claimed.current_run_id,profile=claimed.assignee,mode=mode,
                 exit_code=code,status=current.status,owner=current.assignee if current.status=='review' else 'cto' if card['author'] in ('cto','techlead') else 'techlead',
                 next_action='Independent review' if current.status=='review' else 'Resume author changes' if current.status=='ready' else 'Inspect card evidence and proceed to integration or diagnosis')
        time.sleep(15)
if __name__=='__main__':
    from product_dispatcher import main as dispatch
    dispatch()
