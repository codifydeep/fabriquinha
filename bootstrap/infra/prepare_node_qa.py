import json,sqlite3
from pathlib import Path
root=Path('/private/tmp/hermes-node-qa-review');root.mkdir(exist_ok=True)
if (root/'packet.json').exists():raise RuntimeError('QA already prepared')
db=sqlite3.connect('file:/private/tmp/hermes-product-agent-trial-01/node-publication.db?mode=ro',uri=True)
merge=json.loads(db.execute("SELECT value FROM receipts WHERE key='merge'").fetchone()[0])
deploy=json.loads(db.execute("SELECT value FROM receipts WHERE key='deploy-smoke'").fetchone()[0])
assert merge['merge']==deploy['commit'] and deploy['smoke_passed']
packet=dict(kind='qa',head=merge['merge'],base=merge['base'],merge=merge,operator_smoke=deploy,
            purpose='Independent fixture QA. Does not certify Truco or prior-version rollback.')
(root/'packet.json').write_text(json.dumps(packet,indent=2));db.close()
print(json.dumps(dict(prepared=True,commit=packet['head'])))
