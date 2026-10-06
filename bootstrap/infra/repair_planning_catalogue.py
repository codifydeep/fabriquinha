"""One-shot operator repair in isolated database; persistent maintenance stays on."""
import json
import os
from pathlib import Path
import sqlite3
from hermes_cli import kanban_db as kb

board = Path('/opt/data/kanban/boards/truco-online-r2-20260911')
os.environ['HERMES_ALLOWED_KANBAN_BOARD'] = board.name
fence = board / 'MAINTENANCE'
assert fence.exists()
source = sqlite3.connect(board / 'kanban.db')
backup = Path('/opt/data/governance/planning-catalogue-failure.db')
assert not backup.exists(), 'Repair already recorded; inspect before rerunning.'
with sqlite3.connect(backup) as dest: source.backup(dest)
db = sqlite3.connect(':memory:'); db.row_factory = sqlite3.Row
source.backup(db)
cards = json.loads((board / 'planning.json').read_text())['cards']
note = ('Operator infrastructure repair 0.21.34: planning_read/planning_write now in the actual model catalogue; '
        'kanban_show context shadowing fixed. Regression reproduced on 0.21.33; native catalogue test passed on 0.21.34. '
        'No product implementation or review approved. Resume original card with new execution; preserve failed run.')
try:
    for task in db.execute('SELECT id,status,current_run_id,title FROM tasks').fetchall():
        if task['id'] in cards and task['status'] in ('running', 'blocked'):
            if task['status'] == 'running':
                assert kb.block_task(db, task['id'], reason='Infrastructure catalogue defect; worker stopped by operator.',
                                     kind='capability', expected_run_id=task['current_run_id'])
            kb.add_comment(db, task['id'], 'operator', note)
            assert kb.unblock_task(db, task['id'])
        elif task['id'] not in cards and task['title'].startswith('INCIDENT-'):
            kb.block_task(db, task['id'], reason='Infrastructure fix installed; awaiting successful independent review of source. Do not close on respawn.', kind='capability')
            kb.add_comment(db, task['id'], 'operator', note)
    assert fence.exists(), 'Maintenance must remain active during operator repair.'
    db.backup(source)
finally:
    db.close(); source.close()
print(json.dumps(dict(repaired=True, preserved_failure_backup=str(backup), maintenance=True)))
