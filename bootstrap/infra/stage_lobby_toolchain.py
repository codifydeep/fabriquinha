"""Bind an actual host preflight to the still-unstarted product registration."""
import hashlib,json,os,shutil,sqlite3
from pathlib import Path
control=Path('/control');board=Path('/opt/data/kanban/boards/truco-online-lobby-20260918')
assert not (control/'controller.db').exists(), 'Do not change a running/seeded controller'
with sqlite3.connect(board/'kanban.db') as db:
    assert db.execute('SELECT COUNT(*) FROM task_runs').fetchone()[0]==0
assert (board/'MAINTENANCE').exists()
cfg=json.loads((control/'config.json').read_text())
assert cfg==json.loads((board/'product-adapter.json').read_text())
proof=json.loads(Path('/input/product-launch/lobby-toolchain-preflight.json').read_text())
files=next(iter(cfg['cards'].values()))['files']
assert proof['passed'] and proof['exit_code']==0
assert proof['snapshot']=={name:hashlib.sha256(content.encode()).hexdigest() for name,content in files.items()}
shutil.copy2(control/'config.json',control/'config.before-node22-preflight.json')
cfg['image']=proof['image']
for path in (control/'config.json',board/'product-adapter.json'):
    path.write_text(json.dumps(cfg,ensure_ascii=False,indent=2)+'\n')
os.chown(board/'product-adapter.json',10000,10000)
(control/'toolchain-preflight.json').write_text(json.dumps(proof,indent=2)+'\n')
print(json.dumps(dict(preflight_bound=True,image=cfg['image'],workers_started=False)))
