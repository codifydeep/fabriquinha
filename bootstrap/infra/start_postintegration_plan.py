"""Start only the bounded reconciliation, preserving product fence."""
import json,socket,sqlite3
from pathlib import Path
from coordination_store import CoordinationStore
root=Path('/opt/data');path=root/'governance/execution.json';s=json.loads(path.read_text())
b=root/'kanban/boards'/s['board'];task=s['postintegration_plan']['task']
assert s['phase']=='POSTINTEGRATION_PREPARED' and (b/'MAINTENANCE').exists()
assert not s['product_dispatch_enabled'] and not s['implementation_dispatch_enabled']
with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as client:
    client.settimeout(15);client.connect('/run/review-control/controller.sock');client.sendall(b'{"operation":"planning_readiness"}\n')
    with client.makefile('rb') as stream:ready=json.loads(stream.readline(65536))
assert ready.get('ready') and ready['attempt']==s['attempt'],ready
with sqlite3.connect(b/'kanban.db') as db:
    assert not db.execute('SELECT 1 FROM tasks WHERE current_run_id IS NOT NULL').fetchone()
    assert db.execute('SELECT status,assignee FROM tasks WHERE id=?',(task,)).fetchone()==('ready','techlead')
s.update(phase='PLANEJAMENTO_DOCUMENTAL_ATIVO',next_action='Tech Lead reconciles H1-H4 in bounded plan correction, CTO reviews. Brief approval verified; product adapter and native graph gates remain pending.')
path.write_text(json.dumps(s,ensure_ascii=False,indent=2)+'\n')
store=CoordinationStore(root/'governance/coordination.db')
try:
    store.enqueue(s['attempt'],'postintegration-start-'+task,json.dumps(dict(profile='techlead',chat_id=s['telegram_chat_id'],text=
        f'🔧 {task}: Tech Lead applies 13 exact plan corrections; CTO reviews independently. CEO brief approval verified in durable ledger; no repeated approval requested. '
        '21-node proposed DAG and review matrix passed structural checks. Product execution remains fenced until adapter/worktree/TDD/PR validation and reviewed graph activation.')))
finally:store.close()
(b/'MAINTENANCE').rename(b/'MAINTENANCE.before-postintegration')
print(json.dumps(dict(started=True,task=task,implementation_allowed=False)))
