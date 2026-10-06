"""Export approved immutable source with explicit, separately reviewed packaging."""
import json,subprocess
from pathlib import Path
ROOT=Path(__file__).parents[1]/'product-launch/lobby-publication/backend'
ROOT.mkdir(exist_ok=True)
code="import sqlite3,json;from product_publication import approved_packet;print(json.dumps(approved_packet(sqlite3.connect('/control/controller.db'),sqlite3.connect('/board/kanban.db'),'truco-restart-20260911','t_47a4ef4c')))"
packet=json.loads(subprocess.check_output(['docker','exec','truco-online-lobby-controller','python','-c',code],text=True))
for name,text in packet['files'].items():
    if name=='package.json':continue
    path=ROOT/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text)
(ROOT.parent/'backend-source-proof.json').write_text(json.dumps(packet,indent=2)+'\n')
print('Approved server and tests exported unchanged; package manifest is a new PR-reviewed artifact.')
