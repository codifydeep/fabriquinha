"""Present controller policy concisely without altering brief/proposals/history.

This is transport recovery, not a model retry, technical approval or scope waiver.
Only a pre-dispatch Tech Lead context overflow can resume once after native proof.
"""
import copy
import hashlib
import json


def present(context,full_policy,compact_policy):
    if len(context)<=8000:return context,None
    if (not full_policy.startswith('\n\nCONTROLLER-VERIFIED CAPABILITIES:')
            or not compact_policy.startswith('\nCONTROLLER CONTRACT:')
            or context.count(full_policy)!=1 or len(compact_policy)>=len(full_policy)):
        raise ValueError('exact controller policy presentation required')
    before,after=context.split(full_policy)
    effective=before+compact_policy+after
    if len(effective)>8000:raise ValueError('planning context exceeds issue limit')
    digest=lambda text:hashlib.sha256(text.encode()).hexdigest()
    return effective,{'operation':'planning_policy_presentation_v1',
        'original_sha256':digest(context),'effective_sha256':digest(effective),
        'original_characters':len(context),'effective_characters':len(effective),
        'unchanged_before_sha256':digest(before),'unchanged_after_sha256':digest(after),
        'brief_proposals_history_unchanged':True,'delivery_approval':False}


def resume(ledger,selection,registry,cli,namespace,*,observe=None):
    if (not ledger or ledger.get('stage')!='blocked' or ledger.get('active')!='techlead'
            or ledger.get('category')!='ValueError:planning context exceeds issue limit'
            or ledger.get('context_presentation_recovery')
            or ledger.get('issues',{}).get('techlead')
            or set(ledger.get('outputs',{}))!={'product','cto'}):return None
    if (not selection['configuration_sha256']
            or ledger.get('configuration_sha256')!=selection['configuration_sha256']
            or ledger.get('base_sha')!=selection['base_sha']
            or ledger.get('brief_sha256')!=hashlib.sha256(selection['brief'].read_bytes()).hexdigest()):
        raise ValueError('planning presentation source identity drift')
    if any(item['title'].startswith(ledger['name']+' — techlead')
           for item in cli('list')['issues']):
        raise ValueError('planning presentation cannot replace an existing issue')
    from planning_intake import parse_proposal
    if observe is None:
        from memory_native import observe
    proofs={}
    for role in ('product','cto'):
        source=ledger['outputs'][role]
        proof,output=observe(source['task_id'],registry['agents'][role],namespace,cli)
        if (proof['content_sha256']!=source['content_sha256']
                or parse_proposal(output,role)!=source['proposal']):
            raise ValueError('planning presentation native source drift')
        proofs[role]=proof
    revised=copy.deepcopy(ledger)
    revised['context_presentation_recovery']={'operation':'native_pre_dispatch_transport_recovery_v1',
        'prior_incident':{k:ledger.get(k) for k in ('stage','active','category','owner','next_action')},
        'native_sources':proofs,'no_agent_restarted':True,'delivery_approval':False}
    revised.update(stage='recovering_context_presentation',owner='techlead')
    revised.pop('category',None);revised.pop('next_action',None)
    return revised
