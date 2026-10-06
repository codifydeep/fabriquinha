from pathlib import Path

TARGET = Path('/opt/hermes/hermes_cli/kanban_db.py')
ANCHOR = '    # Gate: verify created_cards BEFORE the main write txn.'
BLOCK = '''    # Runtime proof, independent of the reviewer's prose.
    from delivery_gate import check_delivery
    delivery_error = check_delivery(conn, task_id)
    if delivery_error:
        with write_txn(conn):
            _append_event(conn, task_id, "completion_blocked_delivery_evidence",
                          {"reason": delivery_error}, run_id=expected_run_id)
        raise ValueError(delivery_error)

'''

def apply(source):
    if BLOCK in source:
        return source
    if source.count(ANCHOR) != 1:
        raise ValueError('unknown complete_task source; refusing patch')
    return source.replace(ANCHOR, BLOCK + ANCHOR)

if __name__ == '__main__':
    TARGET.write_text(apply(TARGET.read_text()))
