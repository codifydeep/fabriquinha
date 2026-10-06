"""Release only the verified policy diagnosis after controller readiness."""
import json, socket, sqlite3
from pathlib import Path
from coordination_store import CoordinationStore

root=Path('/opt/data'); state=json.loads((root/'governance/execution.json').read_text())
board=root/'kanban/boards'/state['board']; repair=state['publication_policy_repair']
assert (board/'MAINTENANCE').exists()
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
    store.enqueue(state['attempt'],'publication-policy-repair-'+repair['fingerprint'],json.dumps(dict(
        profile='techlead',chat_id=state['telegram_chat_id'],text=
        f'🔧 GitHub policy repaired: only linear-history requirement removed; CI, independent review and force-push/deletion protections preserved. '
        f'Real preflight passed. CTO {repair["spike"]} will verify and may resume {repair["source"]}. '
        'One additional recovery authorized for this exact block. No merge or release success declared.')))
finally: store.close()
(board/'MAINTENANCE').rename(board/'MAINTENANCE.before-publication-policy-repair')
print('Policy recovery released; source still requires independent review and merge receipt.')
