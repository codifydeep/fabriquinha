"""Maintenance-only board projection. Child completion is not release delivery."""
import json
import time
import urllib.request
try:
    import u3_lifecycle_reconciliation as lifecycle, u3_work_proposal as work
except ImportError:
    from broker import u3_lifecycle_reconciliation as lifecycle, u3_work_proposal as work


def description(intent):
    return intent['original_description']+'\n\nCONTROLLER MAINTENANCE RECEIPT '+intent['receipt_sha256']+'\n'+json.dumps(dict(
        root=intent['root'],original_issue_id=intent['original_issue_id'],
        maintenance_status='lifecycle_reconciled',historical_tdd_red=False,
        release_homologated=False,dependency_activation_allowed=False,
        result='Scheduling authority suspended; complete original state preserved. NOT product delivery.'),sort_keys=True)


def publish(intent, effects):
    issue=effects.get(intent['issue_id']);parent=effects.get(intent['parent_id'])
    expected=description(intent)
    if (issue.get('id')!=intent['issue_id'] or issue.get('parent_issue_id')!=intent['parent_id']
            or issue.get('assignee_id') is not None or parent.get('id')!=intent['parent_id']):
        raise ValueError('exact unassigned maintenance card and parent required')
    # A successful write may create the parent's system child_done rule.
    # On a lost acknowledgment, reconcile the committed projection before
    # applying pre-write wakeup checks: no second write or new event is needed.
    if issue.get('status')=='done' and issue.get('description')==expected:
        return dict(stage='published',receipt_sha256=intent['receipt_sha256'],release_homologated=False)
    if (parent.get('assignee_id') is not None
            or any(w.get('enabled') is True for key in (intent['issue_id'],intent['parent_id']) for w in effects.wakeups(key))):
        raise ValueError('unassigned parent without active wakeups required before writing')
    if issue.get('status')!='todo' or issue.get('description')!=intent['original_description']:
        raise ValueError('native maintenance projection drift')
    effects.put(intent['issue_id'],dict(status='done',description=expected,suppress_run=True))
    observed=effects.get(intent['issue_id'])
    if observed.get('status')!='done' or observed.get('description')!=expected:
        raise ValueError('exact persisted maintenance projection required')
    return dict(stage='published',receipt_sha256=intent['receipt_sha256'],release_homologated=False)


class Effects(work.Effects):
    def get(self,key):return self.issues.request('/issues/'+key)
    def wakeups(self,key):return self.issues.request('/issues/'+key+'/wakeups')
    def put(self,key,body):
        request=urllib.request.Request('http://backend:8080/api/issues/'+key,
            headers={'Authorization':'Bearer '+self.settings['token'],
                     'X-Workspace-ID':self.settings['workspace_id'],'Content-Type':'application/json'},
            data=json.dumps(body).encode(),method='PUT')
        with urllib.request.urlopen(request,timeout=10) as response:return json.load(response)


def tick(b, *, now=None):
    now=time.time() if now is None else now
    with b.LOCK,b.db() as con:
        con.execute('CREATE TABLE IF NOT EXISTS lifecycle_publications(issue_id TEXT PRIMARY KEY,intent TEXT,state TEXT,next_try REAL)')
        tables={r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {'u3_work_proposals','u3_lifecycle_reconciliations'}<=tables:return
        for row in con.execute('SELECT config,state FROM u3_work_proposals').fetchall():
            config,state=map(json.loads,row)
            if state.get('stage')!='lifecycle_reconciled':continue
            match=[]
            for r in con.execute('SELECT contract,receipt FROM u3_lifecycle_reconciliations').fetchall():
                contract,receipt=map(json.loads,r)
                if contract['work_issue_id']==state['work_issue_id']:match.append((contract,receipt))
            if len(match)!=1:raise ValueError('unique maintenance receipt required')
            contract,receipt=match[0]
            if work.observer.digest(receipt)!=state['receipt_sha256']:raise ValueError('maintenance receipt drift')
            lifecycle.reconcile(con,contract)
            original=dict(state['proposal'],independent_review=state['review'],
                source_sha=config['source_sha'],criteria=config['criteria'],
                original_attempt_status='historically_blocked_not_homologated',
                product_edits_allowed=False,dependency_activation_allowed=False)
            intent=dict(issue_id=state['work_issue_id'],parent_id=config['request']['issue_id'],
                root=contract['root'],original_issue_id=receipt['original_issue_id'],
                receipt_sha256=state['receipt_sha256'],
                original_description='VALIDATED TECHNICAL MAINTENANCE CONTRACT; not product execution approval.\n'+json.dumps(original,sort_keys=True))
            prior=con.execute('SELECT intent FROM lifecycle_publications WHERE issue_id=?',(intent['issue_id'],)).fetchone()
            if prior and json.loads(prior[0])!=intent:raise ValueError('publication intent drift')
            con.execute('INSERT OR IGNORE INTO lifecycle_publications VALUES(?,?,?,?)',
                (intent['issue_id'],json.dumps(intent,sort_keys=True),json.dumps(dict(stage='pending',attempts=0)),now))
        row=con.execute('SELECT * FROM lifecycle_publications WHERE next_try<=? LIMIT 1',(now,)).fetchone()
        if not row:return
        if con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone():return
    intent,state=json.loads(row['intent']),json.loads(row['state'])
    try:
        result=publish(intent,Effects(b));state.update(result)
        delay=1e30
    except Exception as error:
        state['attempts']+=1;state['category']=type(error).__name__
        blocked=isinstance(error,ValueError) or state['attempts']>=2
        state.update(stage='technical_blocked' if blocked else 'pending',
                     next_action='CTO reconciles exact native maintenance projection; never approve product')
        delay=1e30 if blocked else 30
    with b.db() as con:con.execute('UPDATE lifecycle_publications SET state=?,next_try=? WHERE issue_id=?',
        (json.dumps(state,sort_keys=True),now+delay,intent['issue_id']))
