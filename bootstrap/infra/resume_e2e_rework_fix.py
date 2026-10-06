"""Operator restart after rework/injection fix; preserves every prior receipt."""
import json
from pathlib import Path
from hermes_cli import kanban_db as kb
from coordination_store import CoordinationStore
attempt='rehearsal-e2e-20260914'
board=Path('/opt/data/kanban/boards')/attempt
control=Path('/opt/data/governance')/attempt
assert (board/'MAINTENANCE').exists()
assert not json.loads(Path('/opt/data/governance/execution.json').read_text())['product_dispatch_enabled']
db=kb.connect(board/'kanban.db')
try:
    task=kb.get_task(db,'t_6e419787')
    if task.status=='running':
        kb.block_task(db,task.id,reason='Operator maintenance: services stopped; rework controller fix 0.21.23 installed. Not an injected recovery.',kind='capability',expected_run_id=task.current_run_id)
    kb.add_comment(db,task.id,'operator','0.21.23: NOTES boundary whitespace accepted and canonicalized by author tool; no unchanged resubmissions. Preserve accepted Green. e2e_status arms real fault on current claim; prior timeout is NOT injection evidence. After actual interruption, replacement writes NOTES and submits. No approval declared.')
    assert kb.unblock_task(db,task.id)
finally: db.close()
state=json.loads((control/'execution.json').read_text())
store=CoordinationStore(control/'coordination.db')
try:
    store.enqueue(attempt,'operator:rework-fix-0.21.23',json.dumps(dict(profile='techlead',chat_id=state['telegram_chat_id'],text='🔧 Ensaio retomado: correção do NOTES.md, bloqueio de retrabalho sem mudança e leitura segura da identidade do worker. 174 testes e regressões nativas passaram. Agora será exigida a interrupção real, não timeout. Backend t_6e419787; Truco continua bloqueado.')))
finally: store.close()
(board/'MAINTENANCE').rename(board/'MAINTENANCE.rework-fix-released')
print('Resumed backend after operator correction; no success recorded')
