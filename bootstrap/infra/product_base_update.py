"""Deterministic three-way base update; no conflict guessing or force push."""
def merge(old,delivery,new):
    absent=object();result=dict(new)
    for path in set(old)|set(delivery):
        before=old.get(path,absent);ours=delivery.get(path,absent);theirs=new.get(path,absent)
        if ours==before:continue
        if theirs not in (before,ours):raise PermissionError('base conflict requires technical diagnosis: '+path)
        if ours is absent:result.pop(path,None)
        else:result[path]=ours
    return result

def baseline_image(cfg,files,fallback):
    from product_workspace import digest
    from product_recovery import CONFIGS
    wanted=digest({n:files[n] for n in CONFIGS})
    matches={r['image'] for r in cfg.get('enabled_capabilities',{}).values()
             if r.get('config_sha256')==wanted and r.get('validated_receipt') and r.get('image')}
    if matches:return sorted(matches)[0]
    if fallback.get('files') and all(fallback['files'].get(n)==files.get(n) for n in CONFIGS):return fallback['validation_image']
    raise PermissionError('baseline configuration has no qualified image; platform qualification required')

def prepare(c,task,card,packet,head):
    import json
    from hermes_cli import kanban_db as kb
    from product_workspace import Workspace,digest
    from product_claim import NativeClaim
    from product_policy import context
    from product_recovery import CONFIGS,is_test
    key='base-update:'+task+':'+head;child=c.get(key)
    if child:return child
    original=c.source_files(card['base'])
    # Adapter scope may have expanded since this card was registered. A missing
    # newly visible document is not an author-requested deletion.
    old={n:v for n,v in original.items() if n in card.get('publication_source_files',card['files'])}
    new=c.source_files(head)
    image=card['validation_image']
    if any(old.get(n)!=new.get(n) for n in CONFIGS):
        capability=card.get('capability','backend');registered=c.cfg.get('enabled_capabilities',{}).get(capability,{})
        if registered.get('config_sha256')==digest({n:new[n] for n in CONFIGS}):image=registered['image']
        else:
            from product_platform import request_capability
            request_capability(c,dict(parent=card.get('parent_work_item',task),capability=capability,reason='Integrated base changed the validation configuration; qualify a pinned full-project image before revalidation.'),head,task)
            return None
    conflict=None
    try:files=merge(old,packet['files'],new)
    except PermissionError as exc:files=new;conflict=str(exc)
    policy={k:card[k] for k in ('policy_version','capability','risk','author','reviewer') if k in card}
    if 'policy_version' not in policy:
        role={'backend_data':'backend','frontend':'frontend','quality_security':'quality'}
        policy=context(role[card['author']],card['author'],card['reviewer'])
    brief='Base update of independently approved delivery '+task+'. Do not manufacture Red or edit this immutable merged source. Run Green and full suite, then submit for fresh independent review. If integration fails, report the actual evidence so the team creates a correction task. Original TDD receipts remain attached to the previous delivery, never reclassified.\n'+card['brief']
    if conflict:brief='Resolve the evidenced base conflict on the current integrated baseline using new behavioral TDD. Preserve ALL current tests. Read the prior immutable delivery with product_read_reference(path,offset) and port its intent, not stale base files. Independent fresh review required. '+conflict+'\n'+card['brief']
    child=kb.create_task(c.native,title='REVALIDATE — '+kb.get_task(c.native,task).title,assignee=card['author'],body=brief,initial_status='blocked',max_runtime_seconds=1200,max_retries=0,idempotency_key=key)
    protected=[n for n in files if n in CONFIGS or is_test(n)] if conflict else list(files)
    updated=dict(policy,base=head,files=files,protected=protected,brief=brief,autonomous=True,validation_image=image,baseline_image=baseline_image(c.cfg,new,card),
        parent_work_item=card.get('parent_work_item'),base_update_source=dict(task=task,revision=packet['revision'],image=packet['image'],old_base=card['base']),
        tdd_mode='feature' if conflict else 'revalidation',tdd_contract='case-inventory-v2',baseline_files=new,
        reference_delivery=packet['files'] if conflict else {})
    for field in ('reviewed_test_maintenance','removable_empty_artifacts','adapter'):
        if field in card:updated[field]=card[field]
    w=Workspace(c.private,NativeClaim(c.board,c.cfg['attempt'],{child:updated}))
    if not c.private.execute('SELECT 1 FROM product_drafts WHERE task=?',(child,)).fetchone():w.seed(c.cfg['attempt'],child,updated['author'],head,files,protected,updated['reviewer'])
    c.register(child,updated);kb.unblock_task(c.native,child);c.put(key,child);c.put('superseded:'+task,dict(task=child,reason='base_update',head=head))
    kb.add_comment(c.native,task,'techlead','Approved snapshot preserved; new integrated base requires fresh validation/review in '+child+'. Not published or homologated.')
    return child
