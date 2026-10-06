"""Fresh evidence-scoped rehearsal; only run after backup in maintenance."""
import json
import os
import sqlite3
from prepare_validation_cycle4 import BOARD,CONTROL,main

assert (BOARD/'MAINTENANCE').exists()
with sqlite3.connect(BOARD/'kanban.db') as db:
    assert not db.execute("SELECT 1 FROM tasks WHERE status='running'").fetchone()
    old=[r[0] for r in db.execute("SELECT id FROM tasks WHERE status NOT IN ('done','archived')")]
main(cycle=8,old=old)
cards=json.loads((CONTROL/'cycle-8-cards.json').read_text())
path=BOARD/'validation-contracts.json'; contracts=json.loads(path.read_text())
for task in cards.values(): contracts[task]['semantic_docs']=True
path.write_text(json.dumps(contracts,indent=2)); os.chown(path,10000,10000)
print('Semantic context and documentation contract enabled for cycle 8')
