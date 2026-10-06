"""Persistent alert for an idle nonterminal roadmap, never auto-completion."""
import time
from product_workspace import digest

def watch(c,now=None):
    now=int(time.time()) if now is None else now
    if not c.cfg.get('dag_planning'):return
    frontier=c.get('planning-frontier')
    if not frontier:return
    active=any(c.native.execute("SELECT 1 FROM tasks WHERE id=? AND status IN ('ready','review','running')",(task,)).fetchone() for task in c.cfg['cards'])
    if active:
        prior=c.get('planning-idle')
        if prior and prior.get('state')=='WAITING':c.put('planning-idle',dict(prior,state='ACTIVITY_RESUMED',at=now))
        return
    identity=digest(frontier);prior=c.get('planning-idle')
    if not prior or prior.get('frontier_sha256')!=identity or prior.get('state')!='WAITING':
        prior=dict(state='WAITING',frontier_sha256=identity,since=now,alerted=False,owner='techlead',next_action='Reconcile blocked dependencies and integrated delivery ancestry; review remaining scope. Do not mark release or work item complete.',frontier=frontier)
    if now-prior['since']>=600 and not prior['alerted']:
        from product_lane import emit
        emit(c.board,'planning_stalled',task='planning',profile='techlead',next_action=prior['next_action']+' Eligible: '+', '.join(frontier['eligible'])+'; busy: '+', '.join(frontier['busy']))
        prior['alerted']=True
    c.put('planning-idle',prior)
