"""One-time adoption of pending real PR, without editing its content."""
import json,sqlite3,time,shutil
from pathlib import Path
root=Path('/control');board=Path('/board')
with sqlite3.connect(board/'kanban.db') as db:
    assert not db.execute('SELECT 1 FROM tasks WHERE current_run_id IS NOT NULL').fetchone()
    backup=root/('autonomy-backup-'+time.strftime('%Y%m%d-%H%M%S'));backup.mkdir()
    with sqlite3.connect(backup/'kanban.db') as dest:db.backup(dest)
with sqlite3.connect(root/'controller.db') as db,sqlite3.connect(backup/'controller.db') as dest:db.backup(dest)
shutil.copy2(root/'config.json',backup/'config.json')
proof=json.loads(Path('/input/backend-publication.json').read_text())
with sqlite3.connect(root/'autonomy.db') as db:
    db.execute('CREATE TABLE IF NOT EXISTS records(key TEXT PRIMARY KEY,value TEXT)')
    pub=dict(pr=proof['pr'],head=proof['head'],source_task='t_47a4ef4c',author='techlead',state='CI_WAIT',repairs=0)
    db.execute('INSERT OR IGNORE INTO records VALUES(?,?)',('publication:'+str(pub['pr']),json.dumps(pub)))
print(json.dumps(dict(adopted_pr=pub['pr'],backup=str(backup),no_pr_edits=True)))
