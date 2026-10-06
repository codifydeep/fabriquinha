"""Release only registered foundation assessment and two editorial successors."""
import json
from pathlib import Path
import socket
import sqlite3
from coordination_store import CoordinationStore

root=Path('/opt/data'); path=root/'governance/execution.json'; state=json.loads(path.read_text())
board=root/'kanban/boards'/state['board']
assert state['phase']=='CORRECOES_EDITORIAIS_PREPARADAS' and (board/'MAINTENANCE').exists()
assert not state['product_dispatch_enabled'] and not state['implementation_dispatch_enabled']
config=json.loads((board/'planning.json').read_text())
foundation=state['pr_review_task']; card=config['cards'][foundation]
assert card.get('pr_number')==14
with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as client:
    client.settimeout(15); client.connect('/run/review-control/controller.sock')
    client.sendall(b'{"operation":"planning_readiness"}\n')
    with client.makefile('rb') as stream: ready=json.loads(stream.readline(65536))
assert ready.get('ready') and ready['attempt']==state['attempt'],ready
ids=state['editorial_correction_cards']
with sqlite3.connect(board/'kanban.db') as db:
    assert not db.execute('SELECT 1 FROM tasks WHERE current_run_id IS NOT NULL').fetchone()
    for tid in [foundation,*ids.values()]:
        assert db.execute('SELECT status FROM tasks WHERE id=?',(tid,)).fetchone()[0]=='ready'
state.update(phase='PLANEJAMENTO_DOCUMENTAL_ATIVO',foundation_review_task=foundation,
    next_action='Revisar fundação PR14 e duas correções editoriais; conferir pareceres e CI exatos, publicar novos snapshots. Sem merge automático ou implementação.')
path.write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n')
store=CoordinationStore(root/'governance/coordination.db')
try:
    store.enqueue(state['attempt'],'foundation-editorial-start-'+foundation,json.dumps(dict(
        profile='techlead',chat_id=state['telegram_chat_id'],text=
        f'🔎 Fundação PR14: {foundation}, Tech Lead → CTO, SHA {card["head_sha"][:7]}, CI pull_request real verde. '
        f'Correções mínimas: Produto {ids["stories"]} → Tech Lead; Designer {ids["design"]} → Produto. '
        'Conteúdo restante protegido por hash. Dois workers, um por perfil. Sem merge ou liberação de implementação.')))
finally: store.close()
(board/'MAINTENANCE').rename(board/'MAINTENANCE.before-foundation-editorial')
print(json.dumps(dict(started=True,foundation=foundation,editorial=ids,implementation_allowed=False)))
