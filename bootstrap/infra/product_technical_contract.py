"""Independently reviewed technical acceptance refinement, never product scope."""
def validate(packet,spec):
    if not packet.get('technical_contract_revision_allowed'):raise PermissionError('technical revision not registered')
    if not isinstance(spec,dict) or set(spec)!={'target_task','draft_sha256','brief'}:raise ValueError('exact target, draft and replacement technical brief required')
    if spec['target_task']!=packet['target_task'] or spec['draft_sha256']!=packet['draft_sha256']:raise PermissionError('stale technical contract')
    if not isinstance(spec['brief'],str) or not 150<=len(spec['brief'])<=8000:raise ValueError('complete executable technical acceptance required')

def apply(c,task,card,p,incident):
    import json
    packet=json.loads((c.root/'team-packets'/f'{incident}.json').read_text())
    validate(packet,p['specification'])
    if not card.get('prerequisite_for'):raise PermissionError('only implementation prerequisites; never product brief')
    old=card.get('technical_contract_history',[])
    if not any(x['decision_task']==incident for x in old):old=old+[dict(decision_task=incident,previous_brief=card['brief'])]
    updated=dict(card,brief=p['specification']['brief'],technical_contract_history=old)
    c.register(task,updated)
    return updated
