"""Publish auxiliary memory state on its exact release issue, never its status.

A write acknowledgement lost in transit is observed, not blindly replayed.
The journal precedes the single metadata mutation; quoted model text is omitted.
"""
import hashlib
import json
from pathlib import Path
import re
import uuid

from release_eval import save_receipt

KEY='post_delivery_memory_status'
STAGES={'nomination_intent','nominated','intent','admission_deferred',
        'awaiting_native_review','format_recovery_intent','approved','rejected','blocked'}


def value(release,state):
    if not re.fullmatch(r'[A-Z][A-Z0-9-]{2,31}',release) or state.get('stage') not in STAGES:
        raise ValueError('fixed memory flow identity and stage required')
    owner=state.get('owner')
    if owner not in (None,'techlead','cto'):raise ValueError('technical memory owner required')
    review=state.get('curation',{}).get('issue_id')
    if review is not None and str(uuid.UUID(review))!=review:raise ValueError('canonical curation issue required')
    admission=state.get('curation',{}).get('admission')
    if admission not in (None,'capacity','budget'):raise ValueError('fixed admission reason required')
    return json.dumps({'release':release,'stage':state['stage'],'owner':owner,
        'admission':admission,'curation_issue_id':review,'product_delivery_changed':False},sort_keys=True)


def publish(path,release,configuration,issue,state,cli):
    if str(uuid.UUID(issue))!=issue or not re.fullmatch(r'[a-f0-9]{64}',configuration):
        raise ValueError('exact publication target required')
    desired=value(release,state);path=Path(path)
    if path.is_symlink() or (path.exists() and path.stat().st_size>65536):raise ValueError('unsafe memory publication journal')
    binding={'release':release,'configuration':configuration,'issue':issue}
    old=json.loads(path.read_text()) if path.exists() else None
    if old and old.get('binding')!=binding:raise ValueError('memory publication binding drift')
    metadata=cli('metadata','list',issue)
    if (not isinstance(metadata,dict) or metadata.get('planning_run')!=release
            or metadata.get('sequence')!=release+'-DELIVERY'):
        raise ValueError('native release metadata binding mismatch')
    if old and old.get('stage')=='intent':
        if metadata.get(KEY)!=old['value']:
            raise ValueError('observe prior memory metadata write; do not replay')
        old['stage']='confirmed';save_receipt(path,old)
    if metadata.get(KEY)==desired:
        save_receipt(path,{'binding':binding,'value':desired,'stage':'confirmed',
            'value_sha256':hashlib.sha256(desired.encode()).hexdigest(),'delivery_approval':False})
        return 'confirmed'
    journal={'binding':binding,'value':desired,'stage':'intent',
        'value_sha256':hashlib.sha256(desired.encode()).hexdigest(),'delivery_approval':False}
    save_receipt(path,journal)
    try:
        cli('metadata','set',issue,'--key',KEY,'--value',desired,'--type','string')
    except Exception:
        # A future tick may confirm the same exact value, but must not resend.
        observed=cli('metadata','list',issue)
        if observed.get(KEY)!=desired:return 'observation_pending'
    observed=cli('metadata','list',issue)
    if observed.get(KEY)!=desired:return 'observation_pending'
    journal['stage']='confirmed';save_receipt(path,journal)
    return 'confirmed'


def release_status(config,private,state,cli):
    if state.get('stage')=='not_eligible':return 'not_eligible'
    root=Path(private)
    from dependent_sequence import read_json
    sequence=read_json(root/'dependent-sequences'/(config['name']+'-DELIVERY.json'))
    label=config['stages'][-1]['spec']['label']
    if not sequence or sequence.get('stage')!='done':raise ValueError('completed release status target required')
    issue=sequence.get('issues',{}).get(label)
    return publish(root/'memory-status'/(config['name']+'.json'),config['name'],config['sha256'],issue,state,cli)
