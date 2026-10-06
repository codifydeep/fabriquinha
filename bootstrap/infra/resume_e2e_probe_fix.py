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
    assert not db.execute('SELECT id FROM tasks WHERE current_run_id IS NOT NULL').fetchall()
    kb.add_comment(db,'t_f28fce4b','operator','0.21.27: Docker probe lifecycle instrumented with bounded create/start/wait/logs and owned cleanup. Real HTTP validation and injected start failure recovery verified before release. Use e2e_review_validate() and approve only its fresh passed receipt. Historical incidents preserved; operator has NOT approved delivery.')
    assert kb.unblock_task(db,'t_f28fce4b')
    assert kb.get_task(db,'t_f28fce4b').status=='review'
finally: db.close()
state=json.loads((control/'execution.json').read_text()); store=CoordinationStore(control/'coordination.db')
try:
    store.enqueue(attempt,'operator:probe-lifecycle-0.21.27',json.dumps(dict(profile='techlead',chat_id=state['telegram_chat_id'],text='🔧 t_f28fce4b: revisão retomada após correção do probe Docker. Etapas registradas, uma recuperação limitada para falha de infraestrutura e limpeza verificada. QA deve gerar evidência nova; ensaio ainda não aprovado e Truco bloqueado.')))
finally: store.close()
(board/'MAINTENANCE').rename(board/'MAINTENANCE.probe-lifecycle-fix-released')
print('Deployment review resumed without operator approval')
