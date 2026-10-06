"""Native write barrier for archived boards and unrehearsed product attempts."""
import json
import sqlite3
import os
from pathlib import Path


def validate_mutation(conn, execution=Path('/opt/data/governance/execution.json')):
    database = conn.execute('PRAGMA database_list').fetchone()[2]
    if not database:
        return
    board = Path(database).parent
    allowed=os.environ.get('HERMES_ALLOWED_KANBAN_BOARD')
    if allowed and board.name!=allowed:
        raise PermissionError('board is outside this deployment scope')
    if (board / 'READ_ONLY').exists():
        raise PermissionError('archived board is read-only')
    if not execution.exists():
        return
    registry = json.loads(execution.read_text())
    if registry.get('board') != board.name:
        return
    metadata = json.loads((board / 'board.json').read_text())
    if metadata.get('execution_attempt') != registry.get('attempt'):
        raise PermissionError('board belongs to another execution attempt')
    planning=registry.get('planning_dispatch_enabled') and (board/'planning.json').is_file()
    if not registry.get('rehearsal_passed') or not (registry.get('product_dispatch_enabled') or planning):
        raise PermissionError('product work is fenced until the isolated rehearsal passes')
    if (board / 'MAINTENANCE').exists():
        raise PermissionError('product board is in maintenance')
    ledger=execution.parent/'coordination.db'
    try:
        control=sqlite3.connect(ledger.resolve().as_uri()+'?mode=ro',uri=True)
        try:
            state=control.execute('SELECT board,state FROM attempts WHERE id=?',(registry.get('attempt'),)).fetchone()
        finally:
            control.close()
    except sqlite3.Error as exc:
        raise PermissionError('authoritative release ledger unavailable') from exc
    if not state or state[0]!=board.name or state[1] in {'HOMOLOGADA','CANCELADA_PELO_CEO'}:
        raise PermissionError('release is unknown, mismatched or terminal')
