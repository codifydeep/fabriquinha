"""Stale PRs return to fresh immutable delivery; never reuse old attestations."""
def refresh(c,pub,pr):
    from product_autonomy import api,REPO
    old_base=pub.get('release_base')
    if old_base is None:
        pub['release_base']=pr['base']['sha'];c.put('publication:'+str(pub['pr']),pub);return False
    target=pr['base']['sha']
    if target==old_base:return False
    if pr['base']['ref']!='release/v0.1' or not pr['head']['ref'].startswith('codex/') or pr['head']['repo']['full_name']!=REPO:raise PermissionError('base refresh outside registered feature branch')
    if pr['head']['sha']!=pub['head']:raise PermissionError('external head drift')
    from product_publication import approved_packet
    from product_base_update import prepare
    from product_workspace import digest
    task=pub['source_task'];card=c.cfg['cards'][task]
    packet=approved_packet(c.private,c.native,c.cfg['attempt'],task)
    files=c.source_files(pub['head'])
    packet=dict(packet,files=files,revision='pr-head:'+pub['head']+':'+digest(files))
    child=prepare(c,task,dict(card,base=old_base),packet,target)
    if not child:return True
    c.put('stale-pr:'+str(pub['pr']),dict(state='REVALIDATING_BASE',child=child,old_head=pub['head'],new_base=target))
    latest=api(f"pulls/{pub['pr']}")
    if latest['head']['sha']!=pub['head'] or latest['merged']:raise PermissionError('stale PR changed during recovery')
    if latest['state']=='open':
        api(f"issues/{pub['pr']}/comments",'POST',dict(body='Superseded by fresh-base immutable delivery '+child+'. Old source, branch, CI and review remain preserved. New full validation, maintenance attestation and independent review are required; no force-push or stale approval reuse.'))
        api(f"pulls/{pub['pr']}",'PATCH',dict(state='closed'))
    pub.update(state='SUPERSEDED',replacement_task=child);c.put('publication:'+str(pub['pr']),pub)
    return True
