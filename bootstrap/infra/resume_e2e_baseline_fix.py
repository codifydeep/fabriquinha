"""Explicit operator recovery after verified controller correction, not autonomous success."""
import json
from pathlib import Path
from hermes_cli import kanban_db as kb
from coordination_store import CoordinationStore

attempt='rehearsal-e2e-20260914'
board=Path('/opt/data/kanban/boards')/attempt
control=Path('/opt/data/governance')/attempt
assert (board/'MAINTENANCE').exists()
product=json.loads(Path('/opt/data/governance/execution.json').read_text())
assert not product['product_dispatch_enabled']
db=kb.connect(board/'kanban.db')
try:
    assert not db.execute('SELECT 1 FROM tasks WHERE current_run_id IS NOT NULL').fetchone()
    note=('Operator-assisted recovery: image 0.21.22 fixes byte-exact Red baseline comparison. '
          'Actual app.py lacked final newline but AST matched baseline. 170 tests and actual Docker Red '
          'regression passed. Timeout stays 1200s; 40 iterations; Qwen unchanged. '
          'Preserve existing files and run Red, then Green. Old timeout explanation was incorrect. '
          'No release approval or autonomous-recovery credit for this intervention.')
    for task in ['t_6e419787','t_83ca8107','t_d7b4a7ad']:
        kb.add_comment(db,task,author='operator',body=note)
    assert kb.unblock_task(db,'t_6e419787')
finally: db.close()
state=json.loads((control/'execution.json').read_text())
store=CoordinationStore(control/'coordination.db')
try:
    store.enqueue(attempt,'operator:baseline-fix-0.21.22',json.dumps(dict(profile='techlead',chat_id=state['telegram_chat_id'],text=
        '🔧 Backend t_6e419787 retomado após correção do controlador: ausência de newline não invalida mais Red. '
        '170 testes + Red real em Docker passaram. Timeout e Qwen mantidos. Intervenção do operador registrada; '
        'incidente ainda não considerado resolvido e Truco permanece bloqueado.')))
finally: store.close()
(board/'MAINTENANCE').rename(board/'MAINTENANCE.baseline-fix-released')
print('Backend resumed; historical runs/incidents preserved; no success declared')
