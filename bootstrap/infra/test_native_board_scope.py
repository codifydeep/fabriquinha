import os
from pathlib import Path
import tempfile
from hermes_cli import kanban_db as kb

with tempfile.TemporaryDirectory() as tmp:
    root=Path(tmp)
    allowed=root/'rehearsal'
    allowed.mkdir()
    other=root/'product'
    other.mkdir()
    kb.init_db(allowed/'kanban.db')
    kb.init_db(other/'kanban.db')
    os.environ['HERMES_ALLOWED_KANBAN_BOARD']='rehearsal'
    conn=kb.connect(allowed/'kanban.db')
    try:
        kb.create_task(conn,title='isolated',assignee='backend_data')
    finally: conn.close()
    conn=None
    try:
        conn=kb.connect(other/'kanban.db')
        kb.create_task(conn,title='must fail',assignee='backend_data')
    except PermissionError:
        print('PASS: native mutation rejects product board outside rehearsal scope')
    else:
        raise AssertionError('product mutation escaped deployment scope')
    finally:
        if conn: conn.close()
    from board_scope import scoped
    assert scoped([{'slug':'product'},{'slug':'rehearsal'}])==[{'slug':'rehearsal'}]
    source=Path('/opt/hermes/gateway/kanban_watchers.py').read_text()
    assert source.count("__import__('board_scope').scoped")==4
    assert source.count("__import__('board_scope').list_boards")==4
    print('PASS: all native watcher enumerations and fallback lists are scoped')
