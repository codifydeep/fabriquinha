"""Reviewed executable dependency handoff; no completion from diagnosis text."""
import json
from product_policy import context
from product_recovery import CONFIGS,is_test
from product_workspace import Workspace
from product_claim import NativeClaim
from product_capabilities import preflight

def validate(spec):
    if not isinstance(spec,dict) or set(spec)!={'capability','title','brief'}:raise ValueError('exact prerequisite specification required')
    if spec['capability'] not in ('backend','frontend','quality'):raise PermissionError('implementation capability required')
    if not isinstance(spec['title'],str) or not 10<=len(spec['title'])<=200 or not isinstance(spec['brief'],str) or not 100<=len(spec['brief'])<=8000:raise ValueError('bounded actionable prerequisite required')

def create(c,key,record,proposal):
    from hermes_cli import kanban_db as kb
    from product_autonomy import api
    spec=proposal['specification'];validate(spec)
    head=api('git/ref/heads/release/v0.1')['object']['sha']
    registration=c.cfg.get('enabled_capabilities',{}).get(spec['capability'],{})
    preflight(spec['capability'],registration)
    files=c.source_files(head)
    from product_base_update import baseline_image
    image=baseline_image(c.cfg,files,{})
    policy=context(spec['capability']);protected=[n for n in files if n in CONFIGS or is_test(n)]
    tid=kb.create_task(c.native,title=spec['title'],body=spec['brief'],assignee=policy['author'],initial_status='blocked',max_runtime_seconds=1200,max_retries=0,idempotency_key=key+':prerequisite:'+proposal['task'])
    card=dict(policy,base=head,files=files,protected=protected,brief=spec['brief'],autonomous=True,validation_image=image,tdd_contract='case-inventory-v2',tdd_mode='feature',prerequisite_for=record['task'])
    w=Workspace(c.private,NativeClaim(c.board,c.cfg['attempt'],{tid:card}))
    if not c.private.execute('SELECT 1 FROM product_drafts WHERE task=?',(tid,)).fetchone():w.seed(c.cfg['attempt'],tid,card['author'],head,files,protected,card['reviewer'])
    if tid not in c.cfg['cards']:
        c.register(tid,card);kb.unblock_task(c.native,tid)
    record.update(prerequisite_task=tid,state='WAITING_PREREQUISITE_INTEGRATION',owner=card['author'],next_action='Implement, review and integrate prerequisite; controller then creates fresh environment qualification')
    c.put(key,record)

def resume(c,key,record):
    tid=record['prerequisite_task'];seen=set()
    while c.get('superseded:'+tid):
        if tid in seen:raise PermissionError('cyclic supersession')
        seen.add(tid);tid=c.get('superseded:'+tid)['task']
    pubs=[json.loads(r[0]) for r in c.db.execute("SELECT value FROM records WHERE key LIKE 'publication:%'")]
    merged=next((p for p in pubs if p['source_task']==tid and p['state']=='INTEGRATED'),None)
    if not merged:return
    from product_environment import packet_for
    packet=packet_for(c,merged['merge'],'Revalidate the integrated prerequisite on this exact commit. Read work_context and curated knowledge; verify sources. No inherited approval or homologation.')
    task=c.team_task(key+':after-prerequisite:'+merged['merge'],packet,'PLATFORM — Validate environment after integrated prerequisite',author='devops',capability='deployment')
    record.update(task=task,head=merged['merge'],state='REVIEW_REQUIRED',completed_prerequisite=dict(task=tid,commit=merged['merge']),owner='devops',next_action='Independent same-commit environment QA')
    record.pop('prerequisite_task');c.put(key,record)
