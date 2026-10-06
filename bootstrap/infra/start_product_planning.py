"""Release only the registered planning DAG after installed readiness checks."""
import hashlib
import json
from pathlib import Path
import socket
import sqlite3
import yaml
from coordination_store import CoordinationStore

root = Path('/opt/data'); control = root / 'governance'
state = json.loads((control / 'execution.json').read_text())
board = root / 'kanban/boards' / state['board']
assert state['phase'] in ('PLANEJAMENTO_PREPARADO', 'PLANEJAMENTO_DOCUMENTAL_ATIVO') and (board / 'MAINTENANCE').exists()
assert state['rehearsal_passed'] and not state['product_dispatch_enabled']
with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
    client.settimeout(10); client.connect('/run/review-control/controller.sock')
    client.sendall(b'{"operation":"planning_readiness"}\n')
    with client.makefile('rb') as stream: ready = json.loads(stream.readline(65536))
assert ready.get('ready') and ready['attempt'] == state['attempt'] and not ready['implementation_allowed'], ready
manifest = json.loads((control / 'planning-installed-manifest.json').read_text())
for profile in ('produto', 'designer', 'cto', 'techlead', 'backend_data', 'frontend', 'mobile', 'devops', 'quality_security'):
    home = root / 'profiles' / profile; cfg = yaml.safe_load((home / 'config.yaml').read_text())
    assert cfg['model'] == {'default': 'deepseek/deepseek-v4-flash-0731', 'provider': 'openrouter'}
    assert not cfg.get('fallback_model') and cfg['agent']['max_turns'] == 40 and cfg['toolsets'] == ['kanban']
    assert cfg['kanban']['dispatch_in_gateway'] == (profile == 'techlead')
    assert cfg['kanban']['max_in_progress'] == 2 and cfg['kanban']['max_in_progress_per_profile'] == 1
    assert hashlib.sha256((home / 'SOUL.md').read_bytes()).hexdigest() == manifest[profile + '/SOUL.md']
    assert 'HERMES_KANBAN_BOARD=' + board.name in (home / '.env').read_text().splitlines()
with sqlite3.connect(board / 'kanban.db') as db:
    assert not db.execute('SELECT 1 FROM tasks WHERE current_run_id IS NOT NULL').fetchone()
    registered = json.loads((board / 'planning.json').read_text())['cards']
    assert len(registered) == 4
    for tid, title, status in db.execute('SELECT id,title,status FROM tasks'):
        assert tid in registered or (title.startswith('INCIDENT-') and status == 'blocked')
cards = json.loads((control / 'planning-cards.json').read_text())
store = CoordinationStore(control / 'coordination.db')
try:
    store.enqueue(state['attempt'], 'planning-start-20260916', json.dumps(dict(profile='techlead', chat_id=state['telegram_chat_id'], text=
        '📝 Planejamento do Truco v0.1 liberado com DeepSeek. Brief aprovado preservado. '
        f"Produto: {cards['stories']}; CTO: {cards['architecture']}. Depois: Designer {cards['design']} e plano Tech Lead {cards['plan']}. "
        'Cada documento terá revisão independente e snapshot imutável. Implementação, PR/merge e deploy do jogo permanecem bloqueados até validar o caminho real de worktrees. Lobby não significa versão homologada.')))
finally: store.close()
state.update(phase='PLANEJAMENTO_DOCUMENTAL_ATIVO', planning_dispatch_enabled=True,
    implementation_dispatch_enabled=False, next_action='independent document reviews; then validate worktree execution before coding')
(control / 'execution.json').write_text(json.dumps(state, ensure_ascii=False, indent=2) + '\n')
(board / 'MAINTENANCE').rename(board / 'MAINTENANCE.before-planning')
print(json.dumps(dict(started=True, cards=cards, implementation_allowed=False)))
