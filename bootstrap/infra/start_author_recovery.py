"""Release only the prepared CTO recovery after controller readiness."""
import json
from pathlib import Path
import socket
import sqlite3
from coordination_store import CoordinationStore

root=Path('/opt/data');path=root/'governance/execution.json';state=json.loads(path.read_text())
board=root/'kanban/boards'/state['board'];assert (board/'MAINTENANCE').exists()
assert not state['product_dispatch_enabled'] and not state['implementation_dispatch_enabled']
with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as client:
    client.settimeout(15);client.connect('/run/review-control/controller.sock');client.sendall(b'{"operation":"planning_readiness"}\n')
    with client.makefile('rb') as stream:ready=json.loads(stream.readline(65536))
assert ready.get('ready') and ready['attempt']==state['attempt'],ready
with sqlite3.connect(board/'kanban.db') as db:
    assert not db.execute('SELECT 1 FROM tasks WHERE current_run_id IS NOT NULL').fetchone()
    assert db.execute('SELECT status FROM tasks WHERE id="t_3fb67ce0"').fetchone()[0]=='ready'
store=CoordinationStore(root/'governance/coordination.db')
try:
    store.enqueue(state['attempt'],'author-checkpoint-v1-start',json.dumps(dict(profile='techlead',chat_id=state['telegram_chat_id'],text=
        '🔧 Recuperação de autoria instalada. CTO t_3fb67ce0 poderá retomar Designer t_fd99c33d a partir do rascunho salvo, com hash e causa verificados. '
        'Edições pontuais, até 3 gravações por execução, revisão independente obrigatória. Nenhum rascunho apagado ou aprovado automaticamente.')))
finally:store.close()
(board/'MAINTENANCE').rename(board/'MAINTENANCE.before-author-recovery')
print('CTO recovery released; author remains blocked until controller-authorized diagnosis/resume.')
