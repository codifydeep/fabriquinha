"""Resolve cited durable evidence. No filesystem paths, shell or implicit authority."""
import json,re,time
from product_reading import page

def read(db,binding,who,reference,offset):
    if not isinstance(reference,str) or len(reference)>300:raise ValueError('bounded source reference required')
    if re.fullmatch(r'PR:[1-9][0-9]*@[0-9a-f]{40}',reference):
        exists=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='integration_evidence'").fetchone()
        row=db.execute('SELECT receipt FROM integration_evidence WHERE attempt=? AND reference=?',(who['attempt'],reference)).fetchone() if exists else None
        if not row:raise PermissionError('registered exact-commit integration evidence unavailable')
        value=json.loads(row[0])
        if value.get('state')!='INTEGRATED' or value.get('source_task') not in binding.cards:raise PermissionError('integration outside current registered scope')
    elif re.fullmatch(r'card:t_[a-zA-Z0-9]+',reference):
        task=reference.split(':')[1]
        if task not in binding.cards:raise PermissionError('card outside current registered attempt')
        verdicts=[json.loads(r[0]) for r in db.execute('SELECT envelope FROM product_verdicts WHERE attempt=? AND task=? AND state=? ORDER BY review_run DESC LIMIT 5',(who['attempt'],task,'DELIVERED'))]
        decision=db.execute('SELECT proposal,verdict,state FROM team_decisions WHERE task=?',(task,)).fetchone()
        value=dict(card=task,brief=binding.cards[task].get('brief'),reviews=verdicts,team=dict(proposal=json.loads(decision[0]),verdict=json.loads(decision[1]) if decision[1] else None,state=decision[2]) if decision else None)
    elif re.fullmatch(r'review:[0-9a-f]{64}',reference):
        rows=db.execute('SELECT envelope,state FROM product_verdicts WHERE attempt=?',(who['attempt'],)).fetchall()
        value=[dict(envelope=json.loads(raw),state=state) for raw,state in rows if json.loads(raw)['revision']==reference.split(':')[1]]
        if not value:raise PermissionError('review reference unavailable in current attempt')
    elif reference.startswith('knowledge:') and len(reference.split(':'))==3:
        _,attempt,ident=reference.split(':')
        row=db.execute('SELECT entry,proof,superseded_by FROM team_knowledge WHERE attempt=? AND id=?',(attempt,ident)).fetchone()
        if not row:raise PermissionError('reviewed knowledge reference missing')
        entry=json.loads(row[0])
        if attempt!=who['attempt'] and entry['scope']!='project':raise PermissionError('other-release private scope')
        value=dict(entry=entry,proof=json.loads(row[1]),superseded_by=row[2],expired=entry['valid_until']<=time.time(),historical=attempt!=who['attempt'])
    else:raise PermissionError('use registered card:<id>, review:<revision>, knowledge:<attempt>:<id>; arbitrary links are not controller evidence')
    return dict(page({reference:json.dumps(value,ensure_ascii=False)},reference,offset),authority=False)
