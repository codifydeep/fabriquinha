"""Controller-owned binding to native Hermes claim provenance; read-only."""
import json,sqlite3,time
from contextlib import closing
from pathlib import Path

class NativeClaim:
    def __init__(self,board,attempt,cards):
        self.board=Path(board).resolve(strict=True);self.attempt=attempt
        self.cards=json.loads(json.dumps(cards))
    def __call__(self,request):
        if request.get('attempt')!=self.attempt or request.get('task') not in self.cards:raise PermissionError('unregistered attempt/card')
        if (self.board/'MAINTENANCE').exists() or (self.board/'READ_ONLY').exists():raise PermissionError('board paused')
        with closing(sqlite3.connect((self.board/'kanban.db').as_uri()+'?mode=ro',uri=True)) as db:
            db.row_factory=sqlite3.Row
            row=db.execute('SELECT * FROM tasks WHERE id=?',(request['task'],)).fetchone()
            if not row or row['status']!='running' or row['current_run_id']!=request.get('run') or not row['claim_lock'] or row['claim_lock']!=request.get('claim'):
                raise PermissionError('stale native claim')
            run=db.execute('SELECT * FROM task_runs WHERE id=? AND task_id=?',(row['current_run_id'],row['id'])).fetchone()
            if not run or run['status']!='running' or run['ended_at'] is not None or run['profile']!=row['assignee'] or run['claim_lock']!=row['claim_lock']:
                raise PermissionError('native run mismatch')
            if not row['claim_expires'] or row['claim_expires']<=time.time():raise PermissionError('expired claim')
            event=db.execute("SELECT payload FROM task_events WHERE task_id=? AND run_id=? AND kind='claimed' ORDER BY id DESC LIMIT 1",(row['id'],row['current_run_id'])).fetchone()
            if not event:raise PermissionError('claim provenance missing')
            payload=json.loads(event['payload'] or '{}');source=payload.get('source_status')
            if payload.get('lock')!=row['claim_lock'] or payload.get('run_id')!=row['current_run_id']:raise PermissionError('claim event mismatch')
            if source not in (None,'ready','review'):raise PermissionError('unsupported claim origin')
            mode='review' if source=='review' else 'implementation'
            role=self.cards[row['id']]['reviewer' if mode=='review' else 'author']
            if row['assignee']!=role:raise PermissionError('assignment drift')
            return dict(attempt=self.attempt,task=row['id'],run=row['current_run_id'],claim=row['claim_lock'],profile=role,mode=mode)
