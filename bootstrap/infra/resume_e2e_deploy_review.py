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
    active=db.execute('SELECT id,current_run_id FROM tasks WHERE current_run_id IS NOT NULL').fetchall()
    for row in active:
        assert row['id']=='t_3fb24e8f'
        kb.block_task(db,row['id'],reason='Operator stopped services for deploy review/network repair; preserve incident pending actual QA.',kind='capability',expected_run_id=row['current_run_id'])
    kb.add_comment(db,'t_f28fce4b','operator','0.21.26: host URL repaired using the SAME approved image/commit. macOS probe passes 10 checks. Use review_inspect then e2e_review_validate() with no arguments, then complete only after passed=true. Historical hashes are not targets. Old validation attempts preserved; no approval granted by operator.')
    assert kb.unblock_task(db,'t_f28fce4b')
    assert kb.get_task(db,'t_f28fce4b').status=='review'
finally: db.close()
state=json.loads((control/'execution.json').read_text()); store=CoordinationStore(control/'coordination.db')
try:
    store.enqueue(attempt,'operator:deploy-review-fix-0.21.26',json.dumps(dict(profile='techlead',chat_id=state['telegram_chat_id'],text='🔧 Revisão de deploy retomada com alvo automático. URL local corrigida e 10 verificações no macOS aprovadas, mesmo commit. 177 testes passaram. QA final ainda obrigatório; Truco permanece bloqueado.')))
finally: store.close()
(board/'MAINTENANCE').rename(board/'MAINTENANCE.deploy-review-fix-released')
print('Deployment review resumed; incidents and final QA not completed by operator')
