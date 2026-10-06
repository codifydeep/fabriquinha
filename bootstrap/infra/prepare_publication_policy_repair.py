"""One operator-authorized policy repair; release diagnosis, never approve/merge."""
import json, os, shutil, sqlite3, subprocess, time
from pathlib import Path
from hermes_cli import kanban_db as kb
from publication_merge import gh, REPO, policy_preflight
from publication_access import preflight, recovery_evidence
from review_controller import Controller
from review_block_event import review_block_event

BOARD=Path('/opt/data/kanban/boards/truco-online-r2-20260911')
ROOT=Path('/deliveries'); CONTROL=Path('/opt/data/governance')
SOURCE='t_1a271f5b'; SPIKE='t_60ee8ad8'; IMAGE='estudo-hermes-saas:0.21.46'

def main():
    os.umask(0o077)
    state=json.loads((CONTROL/'execution.json').read_text())
    assert not state['product_dispatch_enabled'] and not state['implementation_dispatch_enabled']
    assert not state.get('publication_policy_repair'), 'already prepared'
    with sqlite3.connect(BOARD/'kanban.db') as db:
        assert not db.execute('SELECT 1 FROM tasks WHERE current_run_id IS NOT NULL').fetchone()
        assert db.execute('SELECT status FROM tasks WHERE id=?',(SOURCE,)).fetchone()[0]=='triage'
        assert db.execute('SELECT status FROM tasks WHERE id=?',(SPIKE,)).fetchone()[0]=='blocked'
    backup=CONTROL/('publication-policy-backup-'+time.strftime('%Y%m%d-%H%M%S')); backup.mkdir()
    for path in (BOARD/'planning.json',ROOT/'planning-config.json',CONTROL/'execution.json'): shutil.copy2(path,backup/path.name)
    for path in (BOARD/'kanban.db',ROOT/'controller.db',CONTROL/'coordination.db'):
        with sqlite3.connect(path) as src,sqlite3.connect(backup/path.name) as dest:
            src.backup(dest); assert dest.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    (BOARD/'MAINTENANCE').write_text('Publication policy repair; no product dispatch.\n')
    os.chown(BOARD/'MAINTENANCE',10000,10000)
    before=gh('api',f'repos/{REPO}/branches/main/protection')
    (backup/'github-protection-before.json').write_text(json.dumps(before,indent=2))
    assert before['required_linear_history']['enabled'] is True
    # Preserve every configured control; the API requires a full PUT payload.
    payload={'required_status_checks':{'strict':before['required_status_checks']['strict'],'checks':before['required_status_checks']['checks']},
             'enforce_admins':before['enforce_admins']['enabled'],
             'required_pull_request_reviews':before.get('required_pull_request_reviews'),
             'restrictions':before.get('restrictions')}
    for key in ('required_linear_history','allow_force_pushes','allow_deletions','block_creations',
                'required_conversation_resolution','lock_branch','allow_fork_syncing'):
        payload[key]=False if key=='required_linear_history' else before[key]['enabled']
    result=subprocess.run(['gh','api','--method','PUT',f'repos/{REPO}/branches/main/protection','--input','-'],
        input=json.dumps(payload),text=True,capture_output=True,check=True,
        env=dict(os.environ,GH_CONFIG_DIR='/opt/data/home/.config/gh'),timeout=30)
    after=gh('api',f'repos/{REPO}/branches/main/protection')
    expected=json.loads(json.dumps(before));expected['required_linear_history']['enabled']=False
    assert after==expected, 'unexpected protection drift; remain paused'
    (backup/'github-protection-after.json').write_text(json.dumps(after,indent=2))
    policy_preflight()
    keeper=sqlite3.connect(BOARD/'kanban.db');keeper.execute('SELECT count(*) FROM sqlite_master').fetchone()
    c=Controller(BOARD,ROOT,state['attempt'],'hermes_review_deliveries',IMAGE)
    try:
        proof=preflight(c,SOURCE)
        with sqlite3.connect(BOARD/'kanban.db') as db:
            db.row_factory=sqlite3.Row; block=review_block_event(db,SOURCE)
            evidence=recovery_evidence(c.db,SOURCE,None,block,proof)
        assert evidence['can_retry'] and evidence['category']=='publication_policy_conflict',evidence
        assert not c.db.execute('SELECT 1 FROM approvals WHERE task=?',(SOURCE,)).fetchone()
    finally: c.db.close();keeper.close()
    authorization=dict(task=SOURCE,block_event=block['id'],scope='one_additional_policy_recovery',backup=str(backup))
    config=json.loads((BOARD/'planning.json').read_text()); config['publication_policy_repair']=authorization
    for path in (BOARD/'planning.json',ROOT/'planning-config.json'):
        path.write_text(json.dumps(config,indent=2)+'\n')
    os.chown(BOARD/'planning.json',10000,10000)
    stage=backup/'stage';stage.mkdir();os.environ['HERMES_ALLOWED_KANBAN_BOARD']=stage.name
    with sqlite3.connect(BOARD/'kanban.db') as src,sqlite3.connect(stage/'kanban.db') as dest: src.backup(dest)
    db=kb.connect(stage/'kanban.db')
    try:
        event=db.execute("SELECT id FROM task_events WHERE task_id=? AND kind='blocked' ORDER BY id DESC LIMIT 1",(SPIKE,)).fetchone()[0]
        assert kb.unblock_task(db,SPIKE,expected_block_event=event)
        kb._append_event(db,SOURCE,'publication_policy_repaired',authorization);db.commit()
        with sqlite3.connect(BOARD/'kanban.db') as dest: db.backup(dest)
    finally: db.close()
    repair=dict(source=SOURCE,spike=SPIKE,fingerprint=proof['fingerprint'],backup=str(backup))
    state['publication_policy_repair']=repair
    state['next_action']='CTO verifies repaired GitHub merge policy and resumes preserved review; no merge yet.'
    (CONTROL/'execution.json').write_text(json.dumps(state,indent=2)+'\n');os.chown(CONTROL/'execution.json',10000,10000)
    print(json.dumps(dict(prepared=True,backup=str(backup),preflight=proof['passed'],merge_performed=False,spike=SPIKE)))

if __name__=='__main__': main()
