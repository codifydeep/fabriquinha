"""Publish ONLY independently approved governance. Never waive CI or merge."""
import json
from product_autonomy import Coordinator,api,REPO
from product_workspace import digest

def publish(c,task):
    answer=c.decision(task)
    if not answer or answer[1]['decision']!='approve':raise PermissionError('delivered independent approval required')
    p,v=answer
    if p['action']!='publish_governance':raise PermissionError('governance-only publication')
    expected={'AGENTS.md','scripts/ci/test-integrity-guard.sh','scripts/ci/verify-test-maintenance.py','scripts/ci/test-maintenance-public.pem','.hermes/team/process-policy.json'}
    if set(p['changes']) not in (expected,expected|{'.hermes/team/generated-manifest.json'},expected|{'.hermes/team/generated-manifest.json','docs/governance/company-contract.md'}):raise PermissionError('governance path scope')
    row=c.private.execute('SELECT receipt FROM governance_validation WHERE task=? AND run=? AND proposal_sha=?',(task,v['run'],digest(p))).fetchone()
    if not row or not json.loads(row[0])['passed']:raise PermissionError('actual isolated governance probe required')
    head=api('git/ref/heads/release/v0.1')['object']['sha']
    if head!=p['head']:raise PermissionError('governance approval base changed; review again')
    key='governance-publication:'+digest(p);prior=c.get(key)
    if prior and prior.get('pr'):return prior
    packet=json.loads((c.root/'team-packets'/f'{task}.json').read_text());supersedes=packet.get('supersedes_publication')
    branch=supersedes['branch'] if supersedes else 'codex/process-governance-'+digest(p)[:12]
    parent=supersedes['head'] if supersedes else head
    if supersedes:
        old=api(f"pulls/{supersedes['pr']}")
        if old['state']!='open' or old['base']['sha']!=head or old['base']['ref']!='release/v0.1' or old['head']['repo']['full_name']!=REPO or old['head']['ref']!=branch or not branch.startswith('codex/process-governance-'):raise PermissionError('governance correction scope drift')
        if old['head']['sha'] not in (parent,prior.get('head') if prior else None):raise PermissionError('governance correction head drift')
    if not prior:
        tree=api('git/commits/'+parent)['tree']['sha']
        entries=[dict(path=n,mode='100755' if n.endswith('test-integrity-guard.sh') else '100644',type='blob',content=s) for n,s in p['changes'].items()]
        tree=api('git/trees','POST',dict(base_tree=tree,tree=entries))['sha']
        commit=api('git/commits','POST',dict(tree=tree,parents=[parent],message='chore: independently reviewed team process and test-maintenance governance'))['sha']
        prior=dict(head=commit,base=head,branch=branch,task=task,proposal_sha256=digest(p),review=v,probe=json.loads(row[0]));c.put(key,prior)
    refs=api('git/matching-refs/heads/'+branch)
    if not refs:api('git/refs','POST',dict(ref='refs/heads/'+branch,sha=prior['head']))
    elif supersedes and len(refs)==1 and refs[0]['object']['sha']==parent:api('git/refs/heads/'+branch,'PATCH',dict(sha=prior['head'],force=False))
    elif len(refs)!=1 or refs[0]['object']['sha']!=prior['head']:raise PermissionError('governance branch drift')
    prs=api('pulls?state=all&head=codifydeep:'+branch+'&base=release/v0.1')
    pr=prs[0] if prs else api('pulls','POST',dict(head=branch,base='release/v0.1',title='Governance: reviewed test maintenance and effective team policy',body='Prepared by operator; proposed by '+p['author']+' and independently reviewed by '+v['reviewer']+' in '+task+'.\n\nExact proposal: '+digest(p)+'\n\nSeven isolated adversarial integrity checks passed. This is governance bootstrap only. CEO authorized a one-time exception ONLY for the old guard refusing its own modification. No product CI, tests or security checks are waived. Not homologation.'))
    prior.update(pr=pr['number'],url=pr['html_url'],state='AWAITING_REAL_CI_AND_SCOPED_BOOTSTRAP');c.put(key,prior)
    return prior
if __name__=='__main__':
    import sys
    result=publish(Coordinator(),sys.argv[1]);print(json.dumps({k:result[k] for k in ('pr','url','state','head')}))
