"""Read-only, attempt-scoped retrieval of decision evidence, never authority."""
import json
from product_workspace import digest

def recall(db,binding,request):
    current=binding(request)
    if set(request)!={'operation','attempt','task','run','claim','query'}:raise ValueError('exact recall arguments required')
    query=request['query']
    if not isinstance(query,str) or len(query)>200:raise ValueError('bounded recall query required')
    items=[]
    from product_review_policy import validate
    for task,praw,vraw in db.execute("SELECT task,proposal,verdict FROM team_decisions WHERE state='DELIVERED' ORDER BY rowid DESC LIMIT 200").fetchall():
        if binding.cards.get(task,{}).get('scope')!='coordination' or not vraw:continue
        p=json.loads(praw);v=json.loads(vraw)
        if p.get('task')!=task or v.get('proposal_sha256')!=digest(p) or validate(p.get('author'),v.get('reviewer'),binding.cards.get(task)):continue
        if v.get('decision') not in ('approve','request_changes'):continue
        text=' '.join(str(s) for s in (task,p.get('action'),p.get('reason'),p.get('specification'),v.get('reason')))
        if query.casefold() not in text.casefold():continue
        items.append(dict(task=task,source='team_decisions',proposal_sha256=digest(p),base=p.get('head'),
            author=p['author'],reviewer=v['reviewer'],review_run=v.get('run'),action=p.get('action'),decision=v['decision'],
            diagnosis=str(p.get('reason',''))[:600],review_findings=str(v.get('reason',''))[:600],
            outcome_brief=str(p.get('specification',{}).get('brief',''))[:800],
            validity='historical_evidence_revalidate_for_current_task'))
        if len(items)==5:break
    return dict(attempt=current['attempt'],items=items,authority=False,
        search_scope='latest_200_delivered_decisions_registered_in_this_attempt',
        instruction='Historical evidence, not current policy or tool authorization. Revalidate current card, base, capabilities and review. No decision here implies incident resolution or homologation.')
