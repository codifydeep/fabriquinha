"""Apply only the independently approved build capability; preserve full pre-change draft."""
import json
from product_workspace import digest
from product_recovery import CONFIGS
from product_validation_jobs import schema

def prepare(coordinator,task,card,proposal,incident):
    db=coordinator.private;schema(db)
    db.execute('CREATE TABLE IF NOT EXISTS product_config_transitions(job TEXT PRIMARY KEY,task TEXT,before_files TEXT,before_protected TEXT,before_version INTEGER,after_sha TEXT)');db.commit()
    job=digest(dict(operation='enable_shared_build',proposal=proposal))
    row=db.execute('SELECT result,state,error FROM product_validation_jobs WHERE id=?',(job,)).fetchone()
    draft=db.execute('SELECT version,files,protected FROM product_drafts WHERE attempt=? AND task=?',(coordinator.cfg['attempt'],task)).fetchone()
    files=json.loads(draft[1])
    transition=db.execute('SELECT after_sha FROM product_config_transitions WHERE job=?',(job,)).fetchone()
    if not transition and digest(files)!=proposal['specification']['draft_sha256']:raise PermissionError('build draft changed before approval application')
    if not row:
        request=dict(approval_task=incident,approval_sha=digest(proposal),head=proposal['head'],target_task=task,draft_sha256=digest(files),files={n:files[n] for n in CONFIGS})
        with db:db.execute('INSERT INTO product_validation_jobs VALUES(?,?,NULL,?,NULL)',(job,json.dumps(request),'QUEUED'))
        return None
    if row[1]=='FAILED':raise RuntimeError('approved build validation preparation failed: '+str(row[2]))
    if row[1]!='READY':return None
    result=json.loads(row[0])
    if not transition:
        if any(result['configs'][n]!=files[n] for n in CONFIGS if n!='tsconfig.build.json'):raise PermissionError('unauthorized configuration delta')
        from product_build_contract import enable_shared_build
        expected=enable_shared_build(files['tsconfig.build.json'])
        if result['configs']['tsconfig.build.json']!=expected:raise PermissionError('build contract delta mismatch')
        updated=dict(files,**{'tsconfig.build.json':expected});protected=json.loads(draft[2]);protected['tsconfig.build.json']=expected
        with db:
            changed=db.execute('UPDATE product_drafts SET version=version+1,files=?,protected=? WHERE attempt=? AND task=? AND version=? AND files=?',(json.dumps(updated),json.dumps(protected),coordinator.cfg['attempt'],task,draft[0],draft[1]))
            if changed.rowcount!=1:raise PermissionError('concurrent draft change')
            db.execute('INSERT INTO product_config_transitions VALUES(?,?,?,?,?,?)',(job,task,draft[1],draft[2],draft[0],digest(updated)))
    elif transition[0]!=digest(files):raise PermissionError('post-transition draft drift')
    new=dict(card,validation_image=result['image'],files=dict(card['files'],**{'tsconfig.build.json':result['configs']['tsconfig.build.json']}))
    coordinator.register(task,new)
    return new
