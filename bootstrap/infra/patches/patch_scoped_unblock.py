from pathlib import Path
TARGET=Path('/opt/hermes/hermes_cli/kanban_db.py')
OLD='def unblock_task(conn: sqlite3.Connection, task_id: str) -> bool:'
NEW='def unblock_task(conn: sqlite3.Connection, task_id: str, *, expected_block_event: Optional[int] = None) -> bool:'
ANCHOR='    with write_txn(conn):\n        current = conn.execute(\n'
BLOCK='''    with write_txn(conn):
        if expected_block_event is not None:
            latest = conn.execute(
                "SELECT id FROM task_events WHERE task_id=? AND kind IN ('blocked','block_loop_detected') ORDER BY id DESC LIMIT 1",
                (task_id,),
            ).fetchone()
            if not latest or int(latest["id"]) != int(expected_block_event):
                raise ValueError("human response targets an obsolete block occurrence")
        current = conn.execute(
'''


def apply(source):
    if NEW in source:
        return source
    if source.count(OLD)!=1:
        raise ValueError('unknown unblock signature')
    start=source.index(OLD)
    end=source.index('\ndef reopen_review_task',start)
    method=source[start:end]
    if method.count(ANCHOR)!=1:
        raise ValueError('unknown unblock transaction')
    return source[:start]+method.replace(OLD,NEW).replace(ANCHOR,BLOCK)+source[end:]


if __name__=='__main__':
    TARGET.write_text(apply(TARGET.read_text()))
