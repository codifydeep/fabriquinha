"""Explicit bounded reset of failed rehearsal cards; backups are mandatory."""
import os
import sqlite3
from prepare_validation_cycle4 import BOARD,main

assert (BOARD/'MAINTENANCE').exists()
with sqlite3.connect(BOARD/'kanban.db') as db:
    assert not db.execute("SELECT 1 FROM tasks WHERE status='running'").fetchone()
    old=[r[0] for r in db.execute("SELECT id FROM tasks WHERE status NOT IN ('done','archived')")]
# Repair only the shared legacy evidence directory, not the immutable store.
evidence=BOARD/'evidence'
assert evidence.is_dir() and not evidence.is_symlink()
os.chown(evidence,10000,10000)
main(cycle=6,old=old)
