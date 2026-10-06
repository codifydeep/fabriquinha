"""Resolve recovery only from integrated independently reviewed delivery proof."""
import json,time

def integrated(c,pub):
    if pub.get('state')!='INTEGRATED' or not pub.get('merge'):raise PermissionError('integration evidence required')
    lineage=set();task=pub['source_task']
    while task and task not in lineage:
        lineage.add(task);card=c.cfg['cards'].get(task,{})
        task=card.get('base_update_source',{}).get('task') or card.get('original_source_task')
    for key,raw in c.db.execute("SELECT key,value FROM records WHERE key LIKE 'blocked-work:%'").fetchall():
        state=json.loads(raw)
        if not isinstance(state,dict) or state.get('state')!='RESUMED' or state.get('target') not in lineage:continue
        state.update(state='RESOLVED_BY_INTEGRATION',resolution=dict(pr=pub['pr'],commit=pub['merge'],source_task=pub['source_task']),next_action='No recovery action; preserve evidence and continue remaining release scope')
        c.put(key,state)
        for incident in [state.get('incident'),*state.get('prior_incidents',[])]:
            if incident:c.put('resolved-incident:'+incident,state['resolution'])
        from product_memory import Memory
        Memory(c.private).propose(dict(attempt=c.cfg['attempt'],task=pub['source_task'],profile='techlead'),
            dict(subject='recovery-'+state['target'],text='The linked impediment reached independently reviewed integration. Inspect the diagnosis, correction and validation before reusing the approach; resumed workers alone were not resolution evidence.',
                sources=['card:'+state['target'],'PR:'+str(pub['pr'])+'@'+pub['merge']],scope='project',valid_until=int(time.time())+90*86400,supersedes=None))
