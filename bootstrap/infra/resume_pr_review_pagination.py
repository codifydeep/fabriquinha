"""One scoped retry after correcting verified packet truncation, not generic reset."""
import json
from pathlib import Path
from hermes_cli import kanban_db as kb
from coordination_store import CoordinationStore

root=Path('/opt/data'); state=json.loads((root/'governance/execution.json').read_text())
assert state['pr_review_task']=='t_b9aa58d8'
assert not state['product_dispatch_enabled'] and not state['implementation_dispatch_enabled']
board=root/'kanban/boards'/state['board']
db=kb.connect(board/'kanban.db')
try:
    task=kb.get_task(db,state['pr_review_task'])
    assert task.status=='blocked' and task.current_run_id is None
    row=db.execute("SELECT id,payload FROM task_events WHERE task_id=? AND kind='blocked' ORDER BY id DESC LIMIT 1",(task.id,)).fetchone()
    assert row['id']==148 and 'planning_read' in row['payload'] and 'read_file' in row['payload']
    kb.unblock_task(db,task.id,expected_block_event=row['id'])
finally: db.close()
store=CoordinationStore(root/'governance/coordination.db')
try:
    store.enqueue(state['attempt'],'pr-review-pagination-fix-148',json.dumps(dict(profile='techlead',chat_id=state['telegram_chat_id'],text=
        '🔧 '+state['pr_review_task']+': corrigido truncamento do pacote. planning_read agora oferece 22 páginas limitadas, sem read_file/terminal. '
        'Mesmo card retomado; run anterior e bloqueio 148 preservados. CTO revisará o parecer; não há merge automático.')))
finally: store.close()
print('Resumed t_b9aa58d8 after verified pagination fix; no approval granted.')
