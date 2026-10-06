"""Release the registered assessment only after private controller readiness."""
import json
from pathlib import Path
import socket
import sqlite3
from coordination_store import CoordinationStore

root=Path('/opt/data'); path=root/'governance/execution.json'
state=json.loads(path.read_text()); board=root/'kanban/boards'/state['board']
assert state['phase']=='REVISAO_PR_PREPARADA' and (board/'MAINTENANCE').exists()
assert not state['product_dispatch_enabled'] and not state['implementation_dispatch_enabled']
config=json.loads((board/'planning.json').read_text())
card=config['cards'][state['pr_review_task']]
with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as client:
    client.settimeout(15); client.connect('/run/review-control/controller.sock')
    client.sendall(b'{"operation":"planning_readiness"}\n')
    with client.makefile('rb') as stream: ready=json.loads(stream.readline(65536))
assert ready.get('ready') and ready['attempt']==state['attempt'],ready
with sqlite3.connect(board/'kanban.db') as db:
    assert not db.execute('SELECT 1 FROM tasks WHERE current_run_id IS NOT NULL').fetchone()
    assert db.execute('SELECT status,assignee FROM tasks WHERE id=?',(state['pr_review_task'],)).fetchone()==('ready','techlead')
number=card.get('pr_number',19)
integration=bool(card.get('integration_action'))
state.update(phase='REVISAO_PR_EM_ANDAMENTO',next_action=f'Tech Lead e CTO conferem PR #{number}. '+('Integração fixa requer recibo remoto.' if integration else 'Sem merge.')+' Implementação bloqueada.')
path.write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n')
store=CoordinationStore(root/'governance/coordination.db')
try:
    store.enqueue(state['attempt'],'pr-review-start-'+state['pr_review_task'],json.dumps(dict(
        profile='techlead',chat_id=state['telegram_chat_id'],text=
        '🔎 Revisão de PR iniciada: '+state['pr_review_task']+f'. Tech Lead analisa PR #{number}, SHA '+card['head_sha'][:7]+'; CTO revisa o parecer. '
        +(f'Integração PR #{number}: aprovação ativa do CTO aciona executor fixo com verificação de SHA/base/CI e recibo de merge. ' if integration else 'Sem merge. ')
        +'Pacote imutável. Sem liberação da implementação do Truco.')))
finally: store.close()
(board/'MAINTENANCE').rename(board/'MAINTENANCE.before-pr-review')
print(json.dumps(dict(started=True,task=state['pr_review_task'],merge_allowed=False)))
