"""Export only exact controller-approved documents. Never grants PR approval."""
import hashlib
import json
from pathlib import Path
import sqlite3
from immutable_delivery import DeliveryStore
from planning_status import evaluate

board=Path('/opt/data/kanban/boards/truco-online-r2-20260911')
private=Path('/deliveries'); destination=Path('/export/docs/planning/v0.1')
config=json.loads((private/'planning-config.json').read_text())
assert config==json.loads((board/'planning.json').read_text())
with sqlite3.connect((board/'kanban.db').as_uri()+'?mode=ro',uri=True) as db:
    db.row_factory=sqlite3.Row
    status=evaluate(db,config)
assert status['state']=='CONCLUIDO'
proof=sqlite3.connect('file:/deliveries/controller.db?mode=ro',uri=True); proof.row_factory=sqlite3.Row
store=DeliveryStore(private)
files={}; manifest=dict(attempt=config['attempt'],brief_sha256=config['brief_sha256'],scope='reviewed planning only; not implemented software',documents=[])
for item in status['receipts']:
    tid=item['task']; revision=item['revision']
    record=proof.execute('SELECT * FROM approvals WHERE task=? AND revision=? AND review_run=?',(tid,revision,item['review_run'])).fetchone()
    assert record and record['author']==item['author'] and record['reviewer']==item['reviewer']
    store.load(config['attempt'],tid,revision)
    content=(store.path(config['attempt'],tid,revision)/'files/PLAN.md').read_bytes()
    name=config['cards'][tid]['role']+'.md'; files[name]=content
    manifest['documents'].append(dict(item,path=name,sha256=hashlib.sha256(content).hexdigest()))
brief=(private/'planning-brief.md').read_bytes()
assert hashlib.sha256(brief).hexdigest()==config['brief_sha256']; files['approved-brief.md']=brief
files['approvals.json']=(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode()
destination.mkdir(parents=True,exist_ok=True)
for name,content in files.items():
    path=destination/name
    if path.exists(): assert path.read_bytes()==content, 'do not overwrite divergent export'
    else: path.write_bytes(content)
print(json.dumps(manifest,ensure_ascii=False)); proof.close()
