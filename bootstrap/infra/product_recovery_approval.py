"""Recover exact approved maintenance when an old escalation pointer survived."""
import json

def approved_maintenance(c,task,card,sha):
    matches=[]
    for tid,registered in c.cfg['cards'].items():
        if registered.get('scope')!='coordination':continue
        path=c.root/'team-packets'/f'{tid}.json'
        if not path.exists():continue
        packet=json.loads(path.read_text())
        if packet.get('target_task')!=task or packet.get('draft_sha256')!=sha:continue
        answer=c.decision(tid)
        if not answer:continue
        p,v=answer;s=p.get('specification',{})
        if v['decision']=='approve' and p['action']=='maintain_tests' and p['head']==card['base'] and s.get('target_task')==task and s.get('draft_sha256')==sha:
            matches.append(tid)
    if len(matches)>1:raise PermissionError('multiple maintenance approvals require explicit reconciliation')
    return matches[0] if matches else None
