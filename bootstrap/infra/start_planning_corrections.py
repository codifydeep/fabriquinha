"""Release prepared correction DAG; never releases product implementation."""
import json
from pathlib import Path
import socket
from coordination_store import CoordinationStore

root=Path('/opt/data'); path=root/'governance/execution.json'; state=json.loads(path.read_text())
board=root/'kanban/boards'/state['board']
assert state['phase']=='CORRECOES_DOCUMENTAIS_PREPARADAS' and (board/'MAINTENANCE').exists()
assert not state['product_dispatch_enabled'] and not state['implementation_dispatch_enabled']
with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as client:
    client.settimeout(15); client.connect('/run/review-control/controller.sock')
    client.sendall(b'{"operation":"planning_readiness"}\n')
    with client.makefile('rb') as stream: ready=json.loads(stream.readline(65536))
assert ready.get('ready') and ready['attempt']==state['attempt'],ready
state.update(phase='PLANEJAMENTO_DOCUMENTAL_ATIVO',next_action='Corrigir design/ADR/plano conforme parecer PR19, revisar novos snapshots; depois atualizar PR e rever novo SHA.')
path.write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n')
store=CoordinationStore(root/'governance/coordination.db')
try:
    ids=state['planning_correction_cards']
    store.enqueue(state['attempt'],'planning-corrections-r2-start',json.dumps(dict(profile='techlead',chat_id=state['telegram_chat_id'],text=
        f'🛠 Correções do PR #19 iniciadas. Designer: {ids["design"]} → revisão Produto. CTO: {ids["architecture"]} → revisão Tech Lead. '
        f'Plano: {ids["plan"]} → revisão CTO, após novos design/ADR aprovados. '
        'Snapshots anteriores preservados; matriz canônica e DAG terão validação automática. Sem merge ou implementação.')))
finally: store.close()
(board/'MAINTENANCE').rename(board/'MAINTENANCE.before-document-corrections')
print(json.dumps(dict(started=True,cards=state['planning_correction_cards'],implementation_allowed=False)))
