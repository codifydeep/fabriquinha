"""Reviewer findings are durable work input; repeated rejection requires diagnosis."""
from hermes_cli import kanban_db as kb
import re
from difflib import SequenceMatcher

def same_findings(left,right):
    def normalized(text):
        text=text or ''
        text=re.sub(r'^(?:team-decision|product-verdict):[0-9a-f]+\n','',text)
        return ' '.join(text.casefold().split())
    return SequenceMatcher(None,normalized(left),normalized(right)).ratio()>=.85

def pending_changes(native,task,checkpoint=0):
    return native.execute("SELECT id,summary FROM task_runs WHERE task_id=? AND id>? AND outcome='changes_requested' ORDER BY id DESC LIMIT 2",(task,checkpoint)).fetchall()

def contain(native,task,card):
    current=kb.get_task(native,task)
    if current.status!='ready' or not (card.get('autonomous') or card.get('scope')=='coordination'):return False
    changes=pending_changes(native,task,card.get('review_checkpoint',0))
    if len(changes)<2:return False
    if not same_findings(changes[0][1],changes[1][1]):return False
    reason='REVIEW_ESCALATION: two independent change requests since last approved diagnosis. Suspend repeated author dispatch; CTO must resolve acceptance/capability conflict. Latest reviews: '+', '.join(str(r[0]) for r in changes)
    return kb.block_task(native,task,reason=reason,kind='capability')
