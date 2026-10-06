"""Bounded operator setup; agents own proposals, reviews and validation."""
import json,time
from product_autonomy import Coordinator
from product_platform import request_capability
from product_memory import Memory
from hermes_cli import kanban_db as kb

def main():
    c=Coordinator()
    if not (c.board/'DRAIN').exists() or not (c.board/'MAINTENANCE').exists():raise PermissionError('maintenance required')
    task='t_02fd54f5'
    card=c.cfg['cards'][task]
    packet=json.loads((c.root/'team-packets'/f'{task}.json').read_text())
    packet['dependency_contract_clarification']='Dependency maps are DELTAS: maximum eight additions/changes across both maps. Existing omitted dependencies remain unchanged. Never copy the whole package.json; no ^/~ ranges, exact registry semver required. A budget rejection is not proof that a small valid delta was attempted. Inspect actual rejected arguments and submit an evidence-backed minimal change; security and full-suite gates remain mandatory.'
    c.register(task,card,packet)
    native=kb.get_task(c.native,task)
    if native.status=='blocked':
        event=c.native.execute("SELECT id,payload FROM task_events WHERE task_id=? AND kind='blocked' ORDER BY id DESC LIMIT 1",(task,)).fetchone()
        if event[0]!=865 or 'dependency request budget' not in event[1]:raise PermissionError('blocked occurrence drift')
        if not kb.unblock_task(c.native,task,expected_block_event=865):raise PermissionError('resume refused')
        kb.add_comment(c.native,task,'devops','Operator repaired dependency-limit diagnostics and clarified delta semantics in packet. No budget increase, source edits or approval; original CTO must propose exact changes and obtain independent review.')
    deploy=request_capability(c,dict(parent='TDD-01',capability='deployment',reason='Execute real qualification of local Compose and independent QA on already integrated product source; not full-release homologation.'),'e9efdad5b94abbe71522bb2d4d8e54b9b14ab2e0','process-validation-20260920')
    key='operator-lesson-seed-20260920'
    if not c.get(key):
        lesson=Memory(c.private).propose(dict(attempt=c.cfg['attempt'],task='t_49be684d',profile='controller'),dict(
            subject='Executed test identity mapping',text='Technical test-maintenance mappings use complete executed path::fullName strings for both old and new IDs. Unchanged cases are omitted from case_mapping. Bare titles, nested mapping objects and literal unchanged are invalid. Review the referenced independent findings and validation before reuse; this lesson is not permission to weaken tests or approve a delivery.',
            sources=['card:t_49be684d'],scope='project',valid_until=int(time.time())+90*86400,supersedes=None))
        c.put(key,lesson)
    (c.board/'MAINTENANCE').unlink();(c.board/'DRAIN').unlink()
    print(json.dumps(dict(frontend=task,deployment=deploy,lesson=c.get(key),dispatch='resumed',operator_approved_delivery=False)))

if __name__=='__main__':main()
