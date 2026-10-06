"""Durable asynchronous fixed deployment validation; restart uses the same identity."""
import json,sqlite3,threading,time
from pathlib import Path
from product_workspace import digest

def schema(db):
    db.execute('CREATE TABLE IF NOT EXISTS deployment_jobs(id TEXT PRIMARY KEY,request TEXT,state TEXT,receipt TEXT,error TEXT)');db.commit()

def request(db,who,proposal,packet):
    from product_deployment import validate,ADAPTER_VERSION
    validate(proposal['specification'],packet);schema(db)
    key=digest(dict(proposal=digest(proposal),review_run=who['run']))
    for old_id,raw,state,error in db.execute('SELECT id,request,state,error FROM deployment_jobs').fetchall():
        old=json.loads(raw)
        if old_id!=key and digest(old['proposal'])==digest(proposal) and state=='FAILED' and old.get('adapter_version')==ADAPTER_VERSION:
            raise PermissionError('same failed deployment and adapter; platform repair required before retry, preserve proposal and environment')
    job=dict(who=who,proposal=proposal,packet=packet,adapter_version=ADAPTER_VERSION)
    with db:db.execute('INSERT OR IGNORE INTO deployment_jobs VALUES(?,?,?,NULL,NULL)',(key,json.dumps(job),'QUEUED'))
    row=db.execute('SELECT state,receipt,error FROM deployment_jobs WHERE id=?',(key,)).fetchone()
    return dict(job=key,state=row[0],receipt=json.loads(row[1]) if row[1] else None,error=row[2],next_action='Poll this same job. Approval requires PASSED. Infrastructure failure requires a controller repair, not a new proposal/environment. Resume the same proposal in a new review only after an adapter repair; functional failure requires evidenced source correction.')

def infrastructure_failure(db,task):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='deployment_jobs'").fetchone():return None
    for key,raw,error in db.execute("SELECT id,request,error FROM deployment_jobs WHERE state='FAILED' ORDER BY rowid DESC").fetchall():
        job=json.loads(raw)
        if job['proposal']['task']==task and any(marker in (error or '') for marker in ('unknown flag:','loopback port not published','local environment command failed:')):
            return dict(job=key,error=error[:1200],owner='devops',next_action='Repair fixed adapter and resume same proposal review. Do not clone the deployment proposal or environment.')
    return None

def proof(db,who,proposal):
    schema(db);key=digest(dict(proposal=digest(proposal),review_run=who['run']))
    row=db.execute('SELECT state,receipt FROM deployment_jobs WHERE id=?',(key,)).fetchone()
    return json.loads(row[1]) if row and row[0]=='PASSED' else None

def start(root,settings):
    def loop():
        from product_claim import NativeClaim
        from product_deployment import run
        db=sqlite3.connect(root/'controller.db',timeout=15);schema(db)
        with db:db.execute("UPDATE deployment_jobs SET state='QUEUED' WHERE state='RUNNING'")
        while True:
            if (Path(settings['board'])/'MAINTENANCE').exists():time.sleep(3);continue
            row=db.execute("SELECT id,request FROM deployment_jobs WHERE state='QUEUED' ORDER BY rowid LIMIT 1").fetchone()
            if not row:time.sleep(3);continue
            key,raw=row;job=json.loads(raw)
            if job.get('execution_attempts',0)>=2:
                with db:db.execute("UPDATE deployment_jobs SET state='FAILED',error=? WHERE id=?",('Two interrupted fixed executions; DevOps diagnosis required, not another identical restart.',key))
                continue
            job['execution_attempts']=job.get('execution_attempts',0)+1
            with db:db.execute("UPDATE deployment_jobs SET state='RUNNING',request=? WHERE id=?",(json.dumps(job),key))
            try:
                fresh=json.loads((root/'config.json').read_text())
                claim=NativeClaim(settings['board'],fresh['attempt'],fresh['cards']);claim(job['who'])
                result=run(settings['snapshot_root'],job['packet'],job['proposal']);claim(job['who'])
                receipt=dict(result,reviewer=job['who']['profile'],review_run=job['who']['run'])
                with db:db.execute("UPDATE deployment_jobs SET state='PASSED',receipt=? WHERE id=?",(json.dumps(receipt),key))
            except Exception as exc:
                with db:db.execute("UPDATE deployment_jobs SET state='FAILED',error=? WHERE id=?",(type(exc).__name__+': '+str(exc),key))
    threading.Thread(target=loop,daemon=True).start()
