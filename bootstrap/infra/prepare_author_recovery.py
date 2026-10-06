"""Offline enablement of checkpoint recovery; never edits or approves author's draft."""
import json
import os
from pathlib import Path
import shutil
import sqlite3
import time
from planning_drafts import digest
from hermes_cli import kanban_db as kb

ROOT=Path('/opt/data'); PRIVATE=Path('/deliveries'); CONTROL=ROOT/'governance'
BOARD=ROOT/'kanban/boards/truco-online-r2-20260911'

def save(path,data):path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')

def main():
    os.umask(0o077)
    state=json.loads((CONTROL/'execution.json').read_text())
    assert not state['product_dispatch_enabled'] and not state['implementation_dispatch_enabled']
    data=json.loads((BOARD/'planning.json').read_text()); assert data==json.loads((PRIVATE/'planning-config.json').read_text())
    assert not data['cards']['t_fd99c33d'].get('author_recovery_policy'), 'already installed; inspect rather than repeat'
    with sqlite3.connect(BOARD/'kanban.db') as db:
        assert not db.execute('SELECT 1 FROM tasks WHERE current_run_id IS NOT NULL').fetchone()
        assert db.execute('SELECT status,assignee FROM tasks WHERE id="t_fd99c33d"').fetchone()==('blocked','designer')
        assert db.execute('SELECT status,assignee FROM tasks WHERE id="t_3fb67ce0"').fetchone()==('blocked','cto')
    (BOARD/'MAINTENANCE').write_text('Author recovery installation; preserve all drafts and receipts.\n');os.chown(BOARD/'MAINTENANCE',10000,10000)
    backup=CONTROL/('author-checkpoint-backup-'+time.strftime('%Y%m%d-%H%M%S'));backup.mkdir()
    for path in (BOARD/'planning.json',PRIVATE/'planning-config.json',CONTROL/'execution.json'):shutil.copy2(path,backup/path.name)
    for source in (BOARD/'kanban.db',PRIVATE/'controller.db',CONTROL/'coordination.db'):
        with sqlite3.connect(source) as src,sqlite3.connect(backup/source.name) as dest:
            src.backup(dest);assert dest.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    with sqlite3.connect(PRIVATE/'controller.db') as db:
        row=db.execute('SELECT run,content FROM planning_drafts WHERE task="t_fd99c33d"').fetchone();assert row
        (backup/'designer-checkpoint.md').write_text(row[1]); original_hash=digest(row[1])
    data['cards']['t_fd99c33d']['author_recovery_policy']='checkpoint-v1'
    data['cards']['t_fd99c33d']['objective']=(
        'Resume the saved draft, not a blank document. Read planning_read(view="draft") and its pages, '
        'apply only necessary exact replacements with planning_patch(expected_sha,edits), or adopt with edits=[]. '
        'Preserve all flows, LOB criteria, wireframes and accessibility. Primary brief ID is BRIEF-TRUCO-v0.1-R1-20260916. '
        'Historical correction notes may quote old typos. Do not repeatedly rewrite for style: maximum three saves, '
        'then submit to produto for independent review when structural checks pass. No code or fabricated test results.')
    stage=backup/'author-recovery-stage';stage.mkdir();os.environ['HERMES_ALLOWED_KANBAN_BOARD']=stage.name
    with sqlite3.connect(BOARD/'kanban.db') as src,sqlite3.connect(stage/'kanban.db') as dest:src.backup(dest)
    db=kb.connect(stage/'kanban.db')
    try:
        # Stop the previous pattern of an identical full automatic author retry.
        db.execute('UPDATE tasks SET max_retries=1 WHERE id="t_fd99c33d"');db.commit()
        event=db.execute("SELECT id FROM task_events WHERE task_id='t_3fb67ce0' AND kind='blocked' ORDER BY id DESC LIMIT 1").fetchone()
        assert event;kb.unblock_task(db,'t_3fb67ce0',expected_block_event=event[0])
        assert kb.get_task(db,'t_fd99c33d').status=='blocked', 'Only CTO diagnosis is released; never bypass it'
        with sqlite3.connect(BOARD/'kanban.db') as dest:db.backup(dest)
    finally:db.close()
    save(BOARD/'planning.json',data);save(PRIVATE/'planning-config.json',data)
    state.update(author_recovery_backup=str(backup),author_checkpoint_sha256=original_hash,
        next_action='CTO diagnoses saved author checkpoint and may resume designer; no automatic approval. English language support prepared pending CEO scope confirmation.')
    save(CONTROL/'execution.json',state)
    for p in (BOARD/'kanban.db',BOARD/'planning.json',CONTROL/'execution.json'):os.chown(p,10000,10000)
    print(json.dumps(dict(prepared=True,recovery='t_3fb67ce0',source='t_fd99c33d',checkpoint_sha256=original_hash,backup=str(backup))))

if __name__=='__main__':main()
