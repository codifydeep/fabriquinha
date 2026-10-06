import tempfile
from pathlib import Path
from hermes_cli import kanban_db as kb
from triage_recovery import recover

with tempfile.TemporaryDirectory() as tmp:
    path=Path(tmp)/'kanban.db'; kb.init_db(path); conn=kb.connect(path)
    try:
        task=kb.create_task(conn,title='INCIDENT-t_original',assignee='cto',initial_status='blocked')
        conn.execute("UPDATE tasks SET status='triage' WHERE id=?",(task,)); conn.commit()
        assert recover(conn,task)==dict(status='todo',incident_resolved=False)
        assert recover(conn,task)['already_applied']
        assert conn.execute("SELECT count(*) FROM task_events WHERE task_id=? AND kind='specified'",(task,)).fetchone()[0]==1
        product=kb.create_task(conn,title='FEATURE',assignee='backend_data',initial_status='blocked')
        try: recover(conn,product)
        except PermissionError: pass
        else: raise AssertionError('non-diagnostic task accepted')
        print('PASS: real triage -> todo, idempotent; no approval, no reset, no product mutation')
    finally: conn.close()
