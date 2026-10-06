"""Operator-only new rehearsal after verified backup, without old obligations."""
import sqlite3
from prepare_validation_cycle4 import BOARD,main

assert (BOARD/'MAINTENANCE').exists()
with sqlite3.connect(BOARD/'kanban.db') as db:
    assert not db.execute("SELECT 1 FROM tasks WHERE status='running'").fetchone()
    old=[r[0] for r in db.execute("SELECT id FROM tasks WHERE status NOT IN ('done','archived')")]
main(cycle=7,old=old)
