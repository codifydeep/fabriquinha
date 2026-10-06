"""Operator restart after receipt-reader validation, preserving old incidents."""
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
    kb.add_comment(db,'t_6e419787','operator','0.21.24: fixed receipt reader tested before/after restart; no direct coordination.db reads by controller. Preserve Green and NOTES. e2e_status then e2e_submit; obey real fault wait. This intervention is not autonomous recovery or approval.')
    assert kb.specify_triage_task(db,'t_6e419787',author='operator')
finally: db.close()
state=json.loads((control/'execution.json').read_text())
store=CoordinationStore(control/'coordination.db')
try:
    store.enqueue(attempt,'operator:sqlite-fix-0.21.24',json.dumps(dict(profile='techlead',chat_id=state['telegram_chat_id'],text='🔧 SQLite: leitura dos recibos corrigida via serviço restrito, validada após reinício. 175 testes passaram. Backend t_6e419787 retomado; Green, NOTES e PR preservados. Intervenção assistida; ensaio ainda não aprovado.')))
finally: store.close()
(board/'MAINTENANCE').rename(board/'MAINTENANCE.sqlite-fix-released')
print('Backend resumed from triage; receipts preserved')
