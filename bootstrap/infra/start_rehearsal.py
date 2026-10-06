"""Explicit operator start for the current isolated phase; never approves it."""
import json
from pathlib import Path
import subprocess
import yaml
from coordination_store import CoordinationStore

ROOT=Path('/opt/data')
PROFILES=('produto','designer','cto','techlead','backend_data','frontend','mobile','devops','quality_security')
data=json.loads((ROOT/'governance/rehearsal/execution.json').read_text())
product=json.loads((ROOT/'governance/execution.json').read_text())
assert data['attempt']==data['board']=='rehearsal-20260912'
assert not product['product_dispatch_enabled'] and not product['rehearsal_passed']
assert (ROOT/'kanban/boards'/product['board']/'MAINTENANCE').exists()
for profile in PROFILES:
    home=ROOT/'profiles'/profile
    config=yaml.safe_load((home/'config.yaml').read_text())
    assert config['model']=={'default':'qwen3.5:9b','provider':'ollama-local'}
    assert config['kanban']['dispatch_in_gateway']==(profile=='techlead')
    assert config['kanban']['max_in_progress']==2
    assert config['agent']['max_turns']==40
    path=home/'gateway_state.json'
    state=json.loads(path.read_text())
    state.update(desired_state='running',restart_requested=False)
    path.write_text(json.dumps(state))
    subprocess.run(['/command/s6-svc','-u','/run/service/gateway-'+profile],check=True)
store=CoordinationStore(ROOT/'governance/rehearsal/coordination.db')
try:
    store.enqueue(data['attempt'],'operator:start:'+data['phase'],json.dumps(dict(profile='techlead',chat_id=data['telegram_chat_id'],text=
        '🧪 '+data['phase']+' iniciado com Qwen3.5:9b local. Backend → revisão com testes isolados → retrabalho → revisão → QA. '
        'Somente scratch; Truco v0.1 continua bloqueado. Não é homologação. '
        'Status: /kanban@techlead_truco_poc_bot team-status')))
finally: store.close()
print('Start requested for nine gateways; product remains fenced')
