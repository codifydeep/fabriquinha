"""Reviewed deployment work and explicit QA projection, never auto-homologation."""
import json
from product_workspace import digest

def packet_for(c,head,brief):
    pubs=[json.loads(r[0]) for r in c.db.execute("SELECT value FROM records WHERE key LIKE 'publication:%'")]
    integrated=next((p for p in pubs if p.get('merge')==head and p['state']=='INTEGRATED'),None)
    if not integrated:raise PermissionError('deployment needs integrated exact-head provenance')
    ci=c.ci(integrated['head'])
    if not ci or ci['conclusion']!='success':raise PermissionError('actual successful integrated-source CI required')
    source=c.cfg['cards'][integrated['source_task']]
    packet=dict(head=head,files=c.source_files(head),integration=integrated,ci={k:ci[k] for k in ('id','head_sha','conclusion','html_url')},validation_image=source['validation_image'],allowed_actions=['deploy_local'],
        brief=brief,constraints='DevOps proposes {entry,health_path,checks,reason}. entry is compiled dist/*.js; app must honor PORT=8080, HOST=0.0.0.0. checks are [{path,status,contains}] against relative local HTTP paths. No shell, Compose YAML, credentials or external URL. QA reviews immutable proposal and calls team_validate: controller stages exact integrated source in fixed Docker Compose, runs health + HTTP checks + undeploy/restore. Poll the durable job, inspect actual receipt, then decide. This is environment QA, not complete product acceptance or release homologation. No prior-version rollback is claimed by first-deploy restoration.')
    packet['allowed_actions'].append('request_prerequisite')
    packet['prerequisite_contract']='If actual integrated source cannot be deployed, request_prerequisite with exact {capability: backend|frontend|quality,title,brief}. Describe evidence, bounded correction and behavioral TDD acceptance. Independent approval creates implementation work; only integrated delivery triggers a new deploy/QA card. Do not request protected config changes when a source-only solution suffices. A diagnosis alone does not dispatch work.'
    return packet

def dispatch(c,key,head,parent,brief,title):
    packet=packet_for(c,head,brief)
    tid=c.team_task(key,packet,title,author='devops',capability='deployment')
    card=dict(c.cfg['cards'][tid],parent_work_item=parent,environment_delivery=True)
    c.register(tid,card);return tid

def accepted(c):
    result={}
    for tid,card in c.cfg['cards'].items():
        if not card.get('environment_delivery'):continue
        answer=c.decision(tid)
        if not answer or answer[1]['decision']!='approve':continue
        p,v=answer
        from product_deployment_jobs import proof
        receipt=proof(c.private,dict(run=v['run']),p)
        if not receipt or receipt['reviewer']!=v['reviewer'] or receipt['commit']!=p['head']:raise PermissionError('environment QA provenance drift')
        value=dict(task=tid,state='ENVIRONMENT_VALIDATED',parent=card['parent_work_item'],commit=p['head'],proposal_sha256=digest(p),receipt=receipt,homologated=False)
        result[tid]=value;c.put('environment-delivery:'+tid,value)
    return result
