"""Operator resumes the review lane only after real CI has been checked."""
import json
from pathlib import Path
from hermes_cli import kanban_db as kb
from coordination_store import CoordinationStore
attempt='rehearsal-e2e-20260914'; board=Path('/opt/data/kanban/boards')/attempt
control=Path('/opt/data/governance')/attempt
assert (board/'MAINTENANCE').exists()
assert not json.loads(Path('/opt/data/governance/execution.json').read_text())['product_dispatch_enabled']
db=kb.connect(board/'kanban.db')
try:
    assert not db.execute('SELECT 1 FROM tasks WHERE current_run_id IS NOT NULL').fetchone()
    task=kb.get_task(db,'t_6e419787'); assert task.status=='blocked' and task.assignee=='techlead'
    kb.add_comment(db,task.id,'operator','0.21.25: local runner Python installed. Real GitHub CI rerun on exact submitted SHA succeeded. CI is not simulated. Revalidate current snapshot, e2e_merge, then complete only after merged=true. Prior recovery receipts preserved. This maintenance does not approve release.')
    assert kb.unblock_task(db,task.id)
    assert kb.get_task(db,task.id).status=='review'
finally: db.close()
state=json.loads((control/'execution.json').read_text())
store=CoordinationStore(control/'coordination.db')
try:
    store.enqueue(attempt,'operator:ci-fix-0.21.25',json.dumps(dict(profile='techlead',chat_id=state['telegram_chat_id'],text='🔧 Runner corrigido; CI real passou no mesmo commit. Revisão t_6e419787 retomada: validar snapshot, merge controlado, depois deploy/QA. 176 testes passaram. Ensaio ainda não aprovado.')))
finally: store.close()
(board/'MAINTENANCE').rename(board/'MAINTENANCE.ci-fix-released')
print('Review resumed; no merge or approval performed by operator')
