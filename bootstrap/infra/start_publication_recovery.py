"""Start repaired diagnosis only, after installed controller readiness."""
import json
from pathlib import Path
import socket
import sqlite3
from coordination_store import CoordinationStore

root=Path('/opt/data');path=root/'governance/execution.json';state=json.loads(path.read_text())
board=root/'kanban/boards'/state['board'];assert (board/'MAINTENANCE').exists()
repair=state['publication_access_repair']
assert not state['product_dispatch_enabled'] and not state['implementation_dispatch_enabled']
with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as client:
    client.settimeout(15);client.connect('/run/review-control/controller.sock')
    client.sendall(b'{"operation":"planning_readiness"}\n')
    with client.makefile('rb') as stream: ready=json.loads(stream.readline(65536))
assert ready.get('ready') and ready['attempt']==state['attempt'],ready
with sqlite3.connect(board/'kanban.db') as db:
    assert not db.execute('SELECT 1 FROM tasks WHERE current_run_id IS NOT NULL').fetchone()
    assert db.execute('SELECT status FROM tasks WHERE id=?',(repair['spike'],)).fetchone()[0]=='ready'
    assert db.execute('SELECT status FROM tasks WHERE id=?',(repair['source'],)).fetchone()[0]=='triage'
store=CoordinationStore(root/'governance/coordination.db')
try:
    store.enqueue(state['attempt'],'publication-access-repair-'+repair['fingerprint'],json.dumps(dict(
        profile='techlead',chat_id=state['telegram_chat_id'],text=
        '🔧 Executor corrigido: leitura com DAC_READ_SEARCH, volumes read-only e nenhum chmod global. '
        'Preflight real passou nos estados, banco, snapshot, pacote e credenciais (sem expor conteúdo). '
        f'CTO {repair["spike"]} verificará a causa e poderá retomar {repair["source"]}. '
        'Mesmo snapshot, revisão ativa obrigatória. Nenhum merge foi declarado.')))
finally: store.close()
(board/'MAINTENANCE').rename(board/'MAINTENANCE.before-publication-access-repair')
print('CTO recovery started; preserved integration remains in triage until verified resume.')
