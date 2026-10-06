"""Delivery phases are projections, not mutations of historical native outcomes."""
import json,time
from product_workspace import digest

def project(c):
    publications={}
    for key,raw in c.db.execute("SELECT key,value FROM records WHERE key LIKE 'publication:%'").fetchall():
        pub=json.loads(raw);publications[pub['source_task']]=pub
    from product_delivery_lineage import integrated_index
    publications.update(integrated_index(c.cfg['cards'],list(publications.values())))
    items={}
    for tid,card in c.cfg['cards'].items():
        row=c.native.execute('SELECT status,assignee,current_run_id FROM tasks WHERE id=?',(tid,)).fetchone()
        if not row:continue
        status,profile,run=row;pub=publications.get(tid)
        if pub and pub['state']=='INTEGRATED':
            phase='INTEGRATED';owner='techlead';action='Assess remaining work-item scope; integrated through '+pub['source_task']+' / PR'+str(pub['pr'])+'; not automatic work-item acceptance'
        elif c.get('superseded:'+tid):
            replacement=c.get('superseded:'+tid)
            phase='DELIVERY_REPLACED';owner=card['author'];action='Continue preserved work through '+replacement['task']+'; old evidence retained'
        elif c.get('resolved-incident:'+tid):
            phase='RESOLVED_BY_INTEGRATION';owner='techlead';action='Historical incident; retain linked integration evidence'
        elif pub:
            phase='INTEGRATED' if pub['state']=='INTEGRATED' else 'INTEGRATION_PENDING'
            owner='techlead';action='Select next dependency-ready work' if phase=='INTEGRATED' else 'Await exact-head CI/review or repair evidence'
        elif status=='done':
            phase='DECISION_RECORDED' if card.get('scope')=='coordination' else 'PR_REVIEW_RECORDED' if card.get('scope')=='pr_review' else 'SNAPSHOT_APPROVED'
            owner='techlead';action='Apply reviewed operation' if card.get('scope')=='coordination' else 'Publish and integrate; not homologation'
        else:
            phase={'ready':'IMPLEMENTATION_QUEUED','review':'REVIEW_QUEUED','running':'EXECUTING','blocked':'BLOCKED','triage':'DIAGNOSIS_REQUIRED','scheduled':'WAITING_DEPENDENCIES','archived':'HISTORICAL'}.get(status,status.upper())
            owner=profile;action='Execute registered card' if status in ('ready','review','running') else 'Inspect dependencies and linked recovery evidence'
            if status in ('blocked','triage'):
                owner='cto' if card['author'] in ('techlead','cto') else 'techlead'
        value=dict(attempt=c.cfg['attempt'],task=tid,native_status=status,phase=phase,owner=owner,run=run,next_action=action,
                   revision=pub.get('head') if pub else None,integration_commit=pub.get('merge') if pub and pub['state']=='INTEGRATED' else None,delivery_lineage=pub.get('delivery_lineage',[]) if pub else [],homologated=False)
        items[tid]=value
        previous=c.get('projection:'+tid)
        if previous!=value:
            from hermes_cli import kanban_db as kb
            kb.add_comment(c.native,tid,'techlead','Delivery phase: '+phase+' | Owner: '+str(owner)+' | Next: '+action+' | Not homologation.')
            c.put('projection:'+tid,value)
    from product_autonomy import atomic
    atomic(c.board/'delivery-status.json',dict(attempt=c.cfg['attempt'],updated=int(time.time()),items=items,sha256=digest(items)))
