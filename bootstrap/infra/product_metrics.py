"""Derived flow measures; unknown cost/semantic quality stays explicitly unknown."""
import json,time
from product_autonomy import atomic

def export(c):
    now=time.time();queue=[];durations=[];outcomes={}
    for tid,card in c.cfg['cards'].items():
        row=c.native.execute('SELECT status,assignee,created_at FROM tasks WHERE id=?',(tid,)).fetchone()
        if not row:continue
        if row[0] in ('ready','review'):
            event=c.native.execute("SELECT created_at FROM task_events WHERE task_id=? AND kind IN ('review_requested','unblocked','changes_requested','created') ORDER BY id DESC LIMIT 1",(tid,)).fetchone()
            queue.append(dict(task=tid,status=row[0],owner=row[1],age_seconds=max(0,int(now-(event[0] if event else row[2])))))
        for started,ended,outcome in c.native.execute('SELECT started_at,ended_at,outcome FROM task_runs WHERE task_id=?',(tid,)):
            if ended is not None and started is not None:durations.append(max(0,ended-started));outcomes[outcome]=outcomes.get(outcome,0)+1
    incidents=[]
    for key,raw in c.db.execute("SELECT key,value FROM records WHERE key LIKE 'blocked-work:%'"):
        value=json.loads(raw)
        if isinstance(value,dict) and 'state' in value:incidents.append(value)
    pubs=[json.loads(r[0]) for r in c.db.execute("SELECT value FROM records WHERE key LIKE 'publication:%'")]
    data=dict(attempt=c.cfg['attempt'],updated=now,eligible_queue=sorted(queue,key=lambda q:-q['age_seconds']),completed_run_seconds=durations[-100:],run_outcomes=outcomes,
        integrated_increments=sum(p.get('state')=='INTEGRATED' for p in pubs),incidents=len(incidents),resolved_by_integration=sum(i['state']=='RESOLVED_BY_INTEGRATION' for i in incidents),
        token_cost=None,escaped_regressions=None,semantic_quality=None,unknown_reason='These require actual billing and downstream QA evidence; never infer from heartbeat or test count.')
    atomic(c.board/'process-metrics.json',data);return data
