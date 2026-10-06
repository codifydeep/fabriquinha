"""Operator release of the prepared board; never approves the rehearsal."""
import json
from pathlib import Path
import subprocess
import yaml
from hermes_cli import kanban_db as kb
from coordination_store import CoordinationStore
from e2e_controller import ATTEMPT

root = Path('/opt/data')
board = root/'kanban/boards'/ATTEMPT
control = root/'governance'/ATTEMPT
product = json.loads((root/'governance/execution.json').read_text())
assert not product['product_dispatch_enabled'] and not product['rehearsal_passed']
assert (root/'kanban/boards'/product['board']/'MAINTENANCE').exists()
assert (board/'MAINTENANCE').exists(), 'already released; inspect before retrying'
import socket
with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as client:
    client.settimeout(10); client.connect('/run/review-control/controller.sock')
    client.sendall(b'{"operation":"e2e_readiness"}\n')
    with client.makefile('rb') as stream: readiness=json.loads(stream.readline(65536))
assert readiness.get('ready') and readiness.get('attempt')==ATTEMPT, readiness
assert readiness['cards']==json.loads((board/'e2e.json').read_text())['cards']
for profile in ('produto','designer','cto','techlead','backend_data','frontend','mobile','devops','quality_security'):
    home = root/'profiles'/profile
    config = yaml.safe_load((home/'config.yaml').read_text())
    assert config['model'] == {'default':'deepseek/deepseek-v4-flash-0731','provider':'openrouter'}
    assert config['agent']['max_turns'] == 40
    assert config['kanban']['max_in_progress'] == 2
    assert config['kanban']['dispatch_in_gateway'] == (profile == 'techlead')
    assert 'HERMES_KANBAN_BOARD='+ATTEMPT in (home/'.env').read_text().splitlines()
    path = home/'gateway_state.json'
    state = json.loads(path.read_text())
    state.update(desired_state='running', restart_requested=False)
    path.write_text(json.dumps(state))
    subprocess.run(['/command/s6-svc','-u','/run/service/gateway-'+profile],check=True)
cards = json.loads((board/'e2e.json').read_text())['cards']
db = kb.connect(board/'kanban.db')
try:
    assert not db.execute('SELECT 1 FROM tasks WHERE current_run_id IS NOT NULL').fetchone()
    for task in cards.values():
        if kb.get_task(db,task).status == 'blocked': kb.unblock_task(db,task)
finally:
    db.close()
data = json.loads((control/'execution.json').read_text())
data['phase'] = 'ENSAIO_E2E_ATIVO'
data['model_validation'] = dict(model='deepseek/deepseek-v4-flash-0731',provider='openrouter',
    configured_profiles=9,status='E2E_PENDING',max_turns=40,max_workers=2)
(control/'execution.json').write_text(json.dumps(data,indent=2))
store = CoordinationStore(control/'coordination.db')
try:
    store.enqueue(ATTEMPT,'e2e-outbox-probe',json.dumps(dict(profile='techlead',chat_id=data['telegram_chat_id'],text=
        '🧪 Ensaio E2E iniciado com DeepSeek v4 Flash 0731 via OpenRouter: TDD → revisão independente → PR/CI local → Docker/rollback → QA. '
        'Inclui falha controlada de worker, reinício do supervisor e recuperação desta notificação. '
        f"Cards: backend {cards['build']}; deploy {cards['deploy']}; QA {cards['qa']}. "
        'Truco v0.1 permanece bloqueado; iniciar não significa aprovar o ensaio.')))
finally:
    store.close()
(board/'MAINTENANCE').rename(board/'MAINTENANCE.operator-released')
print(json.dumps(dict(started=True,attempt=ATTEMPT,cards=cards,product_released=False)))
