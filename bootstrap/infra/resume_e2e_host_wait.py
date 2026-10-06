"""Operator-assisted recovery of r3; never converts old probes into phase receipts."""
import json
import socket
from pathlib import Path
from hermes_cli import kanban_db as kb
from coordination_store import CoordinationStore
attempt='rehearsal-e2e-20260915-r3'
board=Path('/opt/data/kanban/boards')/attempt
control=Path('/opt/data/governance')/attempt
assert (board/'MAINTENANCE').exists()
assert not json.loads(Path('/opt/data/governance/execution.json').read_text())['product_dispatch_enabled']
with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as s:
    s.settimeout(10); s.connect('/run/review-control/controller.sock')
    s.sendall(b'{"operation":"e2e_host_readiness"}\n')
    with s.makefile('rb') as f: proof=json.loads(f.readline(65536))
assert proof.get('ready'),proof
db=kb.connect(board/'kanban.db')
try:
    assert not db.execute('SELECT id FROM tasks WHERE current_run_id IS NOT NULL').fetchall()
    kb.add_comment(db,'t_fdb04ec9','operator','Operator-assisted recovery: 0.21.30 installed. Local host receipt is fresh for '+proof['commit']+'. Bounded host wait and durable deploy phases installed; no credential/CEO decision required. Revalidate deployment; no old probe converted into a phase receipt. Independent review and QA remain required.')
    assert kb.unblock_task(db,'t_fdb04ec9')
finally: db.close()
state=json.loads((control/'execution.json').read_text()); state['operator_assisted_host_recovery']=proof
(control/'execution.json').write_text(json.dumps(state,indent=2))
store=CoordinationStore(control/'coordination.db')
try: store.enqueue(attempt,'operator:host-wait-0.21.30',json.dumps(dict(profile='techlead',chat_id=state['telegram_chat_id'],text='🔧 t_fdb04ec9: deploy retomado após correção da espera pelo recibo LOCAL do macOS. Etapas duráveis e recuperação limitada instaladas. Intervenção do operador registrada; revisão e QA continuam obrigatórios.')))
finally: store.close()
(board/'MAINTENANCE').rename(board/'MAINTENANCE.host-wait-released')
print(json.dumps(dict(resumed=True,proof=proof,operator_assisted=True)))
