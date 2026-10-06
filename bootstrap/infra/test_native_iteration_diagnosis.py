import tempfile
from pathlib import Path
from hermes_cli import kanban_db as kb
with tempfile.TemporaryDirectory() as tmp:
    path=Path(tmp)/'kanban.db'
    kb.init_db(path)
    conn=kb.connect(path)
    task=kb.create_task(conn,title='test',assignee='backend_data',max_retries=2)
    conn.execute("UPDATE tasks SET status='ready' WHERE id=?",(task,))
    conn.commit()
    assert kb._record_task_failure(conn,task,'Iteration budget exhausted (40/40)',outcome='timed_out')
    assert conn.execute('SELECT status FROM tasks WHERE id=?',(task,)).fetchone()[0]=='blocked'
    assert conn.execute("SELECT count(*) FROM task_events WHERE task_id=? AND kind='gave_up'",(task,)).fetchone()[0]==1
    conn.close()
    print('PASS: first iteration exhaustion requires diagnosis, no blind retry')
