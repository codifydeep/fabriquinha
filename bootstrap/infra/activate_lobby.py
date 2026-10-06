"""Explicit operator activation of registered first product card only."""
import json,os
from pathlib import Path
from hermes_cli import kanban_db as kb
board=Path('/opt/data/kanban/boards/truco-online-lobby-20260918')
cfg=json.loads((board/'product-adapter.json').read_text())
proof=json.loads(Path('/control/toolchain-preflight.json').read_text())
assert proof['passed'] and proof['image']==cfg['image']
db=kb.connect(board/'kanban.db')
assert len(cfg['cards'])==1
for tid in cfg['cards']:
    assert kb.get_task(db,tid).status=='blocked'
    assert kb.unblock_task(db,tid)
(board/'MAINTENANCE').unlink()
p=Path('/opt/data/governance/execution.json');state=json.loads(p.read_text())
state['phase']='CONTROLLED_LOBBY_IMPLEMENTATION'
state['controlled_product_dispatch']['enabled']=True
state['next_action']='TDD-01A implementation → independent immutable review → product PR/CI integration. Other lobby nodes remain behind integrated prerequisites; no generic rehearsals.'
p.write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n');os.chown(p,10000,10000)
print(json.dumps(dict(enabled=list(cfg['cards']),legacy_dispatch_enabled=False,release_homologated=False)))
