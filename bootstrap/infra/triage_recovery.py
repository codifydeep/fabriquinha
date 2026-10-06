"""Supervisor-only bounded transition: diagnostic triage -> todo, without LLM."""
import argparse
import json
import os
from hermes_cli import kanban_db as kb

def recover(conn,task):
    if os.environ.get('HERMES_KANBAN_TASK'): raise PermissionError('workers cannot administer triage')
    row=conn.execute('SELECT * FROM tasks WHERE id=?',(task,)).fetchone()
    if not row or not row['title'].startswith(('INCIDENT-','SPIKE-')) or row['assignee'] not in ('cto','techlead'):
        raise PermissionError('technical diagnosis only')
    if row['current_run_id']: raise PermissionError('live execution cannot be replaced')
    if row['status'] in ('todo','ready'): return dict(status=row['status'],already_applied=True)
    if row['status']!='triage': raise ValueError('not a triaged diagnosis')
    if not kb.specify_triage_task(conn,task,author='durable-supervisor'):
        raise ValueError('triage transition refused')
    return dict(status='todo',incident_resolved=False)

if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--board',required=True); p.add_argument('--task',required=True)
    a=p.parse_args()
    if os.environ.get('HERMES_ALLOWED_KANBAN_BOARD') not in (None,a.board): raise PermissionError('board outside supervisor scope')
    conn=kb.connect(kb.kanban_db_path(board=a.board))
    try: print(json.dumps(recover(conn,a.task)))
    finally: conn.close()
