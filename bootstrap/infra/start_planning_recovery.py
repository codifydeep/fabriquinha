"""Preflight as worker UID, then let the CTO execute the existing recovery card."""
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
from coordination_store import CoordinationStore
from planning_flow import config, claim_allowed

root=Path('/opt/data'); board=root/'kanban/boards/truco-online-r2-20260911'
assert os.geteuid()==10000 and (board/'MAINTENANCE').exists()
state=json.loads((root/'governance/execution.json').read_text())
assert state['planning_dispatch_enabled'] and not state['product_dispatch_enabled']
with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as client:
    client.settimeout(10); client.connect('/run/review-control/controller.sock')
    client.sendall(b'{"operation":"planning_readiness"}\n')
    with client.makefile('rb') as stream: readiness=json.loads(stream.readline(65536))
assert readiness['ready'] and readiness['attempt']==state['attempt']
checks={}
for profile in ('produto','cto','techlead','quality_security'):
    skills=['sdlc-review']+(['grill-me'] if profile=='produto' else [])
    code='import json; from agent.skill_commands import build_preloaded_skills_prompt; p,l,m=build_preloaded_skills_prompt('+repr(skills)+'); print(json.dumps(dict(loaded=l,missing=m)))'
    result=subprocess.run(['/opt/hermes/.venv/bin/python','-c',code],env=dict(os.environ,HERMES_HOME=str(root/'profiles'/profile)),capture_output=True,text=True,check=True)
    checks[profile]=json.loads(result.stdout)
    assert checks[profile]['loaded']==skills and not checks[profile]['missing'], checks
with sqlite3.connect(board/'kanban.db') as db:
    db.row_factory=sqlite3.Row
    assert not db.execute("SELECT 1 FROM tasks WHERE status='running' AND current_run_id IS NOT NULL").fetchone()
    recovery=[dict(r) for r in db.execute("SELECT * FROM tasks WHERE status='ready' AND title LIKE 'SPIKE-%'") if claim_allowed(db,r['id'])]
    assert len(recovery)==1, 'expected one registered CTO recovery'
store=CoordinationStore(root/'governance/coordination.db')
try:
    store.enqueue(state['attempt'],'planning-skills-recovery-20260916',json.dumps(dict(profile='techlead',chat_id=state['telegram_chat_id'],text=
        '🔧 Skills de revisão validadas em Produto, CTO, Tech Lead e QA. CTO retomará a revisão do design pelo incidente registrado, sem recriar a entrega ou conceder aprovação. '
        'Grill-me adaptada ao Produto: até 3 perguntas por rodada, decisões técnicas com CTO, sem reabrir o brief v0.1. Implementação do jogo permanece bloqueada.')))
finally: store.close()
(board/'MAINTENANCE').rename(board/'MAINTENANCE.before-skills-recovery')
print(json.dumps(dict(released=True,preflight=checks,recovery=recovery[0]['id'],implementation_allowed=False)))
