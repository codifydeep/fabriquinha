"""Shared incident exit contract, including registered QA and exact revisions."""
import json
from pathlib import Path


def contracts_for(conn):
    database=conn.execute('PRAGMA database_list').fetchone()[2]
    path=Path(database).parent/'validation-contracts.json' if database else None
    return json.loads(path.read_text()) if path and path.exists() else {}


def completion_error(conn,source,verify):
    contracts=contracts_for(conn)
    required=[source]+[task for task,contract in contracts.items() if contract.get('parent')==source]
    required+=contracts.get(source,{}).get('incident_completion_requires',[])
    deliveries={}
    for task in dict.fromkeys(required):
        row=conn.execute('SELECT status FROM tasks WHERE id=?',(task,)).fetchone()
        if not row or row['status']!='done': return 'awaiting verified completion: '+task
        error=verify(conn,task)
        if error: return task+': '+error
        if contracts.get(task,{}).get('immutable_review'):
            runs=conn.execute('SELECT id,outcome,metadata FROM task_runs WHERE task_id=? ORDER BY id DESC',(task,)).fetchall()
            delivery=next((json.loads(r['metadata'] or '{}')['immutable_delivery'] for r in runs if 'immutable_delivery' in json.loads(r['metadata'] or '{}')),None)
            approved=next((r for r in runs if r['outcome']=='completed' and 'immutable_review' in json.loads(r['metadata'] or '{}')),None)
            proof=json.loads(approved['metadata'])['immutable_review'] if approved else {}
            if (not delivery or proof.get('approved') is not True or proof.get('revision')!=delivery['revision']
                or proof.get('review_run')!=approved['id'] or proof.get('author')!=delivery['author']
                or proof.get('reviewer')!=delivery['reviewer'] or proof.get('author')==proof.get('reviewer')):
                return 'missing exact independent review receipt: '+task
            deliveries[task]=delivery
    for task,delivery in deliveries.items():
        if contracts.get(task,{}).get('parent')==source:
            if source not in deliveries or delivery.get('parent_revision')!=deliveries[source]['revision']:
                return 'QA approval is for a different parent revision: '+task
    return None
