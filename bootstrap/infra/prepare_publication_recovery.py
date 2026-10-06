"""Offline permission repair preflight; releases CTO SPIKE, never source approval."""
import json
import os
from pathlib import Path
import shutil
import sqlite3
import time
from hermes_cli import kanban_db as kb
from review_controller import Controller
from review_block_event import review_block_event
from publication_access import preflight,recovery_evidence

BOARD=Path('/opt/data/kanban/boards/truco-online-r2-20260911')
PRIVATE=Path('/deliveries'); CONTROL=Path('/opt/data/governance')
SOURCE='t_1a271f5b'; SPIKE='t_8bd3203c'
IMAGE='estudo-hermes-saas:0.21.45'


def main():
    os.umask(0o077)
    path=CONTROL/'execution.json'; state=json.loads(path.read_text())
    assert state['attempt']=='truco-restart-20260911'
    assert not state['product_dispatch_enabled'] and not state['implementation_dispatch_enabled']
    assert not state.get('publication_access_repair'), 'already prepared; inspect rather than duplicate'
    with sqlite3.connect(BOARD/'kanban.db') as db:
        assert not db.execute('SELECT 1 FROM tasks WHERE current_run_id IS NOT NULL').fetchone()
        assert db.execute('SELECT status,assignee FROM tasks WHERE id=?',(SOURCE,)).fetchone()==('triage','cto')
        assert db.execute('SELECT status,assignee FROM tasks WHERE id=?',(SPIKE,)).fetchone()==('blocked','cto')
    (BOARD/'MAINTENANCE').write_text('Publication permission repair; preserve evidence and pending merge.\n')
    os.chown(BOARD/'MAINTENANCE',10000,10000)
    backup=CONTROL/('publication-access-backup-'+time.strftime('%Y%m%d-%H%M%S')); backup.mkdir()
    for source in (BOARD/'planning.json',PRIVATE/'planning-config.json',path): shutil.copy2(source,backup/source.name)
    for source in (BOARD/'kanban.db',PRIVATE/'controller.db',CONTROL/'coordination.db'):
        with sqlite3.connect(source) as src,sqlite3.connect(backup/source.name) as dest:
            src.backup(dest); assert dest.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    # A live Kanban writer keeps WAL/SHM available during actual tool execution.
    # Reproduce that condition while paused, without mutating application rows or
    # using immutable=1 (which could ignore committed WAL data).
    keeper=sqlite3.connect(BOARD/'kanban.db')
    keeper.execute('SELECT count(*) FROM sqlite_master').fetchone()
    c=Controller(BOARD,PRIVATE,state['attempt'],'hermes_review_deliveries',IMAGE)
    try:
        access=preflight(c,SOURCE)
        with sqlite3.connect(BOARD/'kanban.db') as db:
            db.row_factory=sqlite3.Row
            block=review_block_event(db,SOURCE)
            evidence=recovery_evidence(c.db,SOURCE,None,block,access)
        assert evidence['can_retry'],evidence
        assert not c.db.execute('SELECT 1 FROM approvals WHERE task=?',(SOURCE,)).fetchone()
    finally: c.db.close(); keeper.close()
    stage=backup/'recovery-stage'; stage.mkdir()
    os.environ['HERMES_ALLOWED_KANBAN_BOARD']=stage.name
    with sqlite3.connect(BOARD/'kanban.db') as src,sqlite3.connect(stage/'kanban.db') as dest: src.backup(dest)
    db=kb.connect(stage/'kanban.db')
    try:
        event=db.execute("SELECT id FROM task_events WHERE task_id=? AND kind='blocked' ORDER BY id DESC LIMIT 1",(SPIKE,)).fetchone()
        assert event and kb.unblock_task(db,SPIKE,expected_block_event=event[0])
        kb._append_event(db,SOURCE,'publication_access_preflight_passed',dict(image=IMAGE,
            fingerprint=access['fingerprint'],scope='read_only_preflight_not_merge',source_block=block['id']))
        db.commit()
        assert kb.get_task(db,SOURCE).status=='triage'
        with sqlite3.connect(BOARD/'kanban.db') as dest: db.backup(dest)
    finally: db.close()
    state['publication_access_repair']=dict(image=IMAGE,backup=str(backup),source=SOURCE,spike=SPIKE,
        fingerprint=access['fingerprint'],failed_paths=evidence['failed_paths'],source_block=block['id'])
    state['next_action']='CTO SPIKE verifies real publication-access preflight and may resume the preserved review; no merge or approval by operator.'
    path.write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n')
    for target in (path,BOARD/'kanban.db'): os.chown(target,10000,10000)
    print(json.dumps(dict(prepared=True,backup=str(backup),source=SOURCE,recovery=SPIKE,
        preflight_passed=True,source_still_triage=True,merge_performed=False)))


if __name__=='__main__': main()
