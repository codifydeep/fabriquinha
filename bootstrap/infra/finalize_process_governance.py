"""Operator-only one-time CEO-authorized bootstrap; NEVER a product merge path."""
import json,hashlib,subprocess
from product_autonomy import Coordinator,api,atomic,REPO
from product_workspace import digest

def finalize(c,task):
    answer=c.decision(task)
    if not answer or answer[1]['decision']!='approve':raise PermissionError('independent delivered review required')
    p,v=answer
    if p['action']!='publish_governance':raise PermissionError('not a governance proposal')
    pub=c.get('governance-publication:'+digest(p))
    if not pub or not pub.get('pr'):raise PermissionError('reviewed publication missing')
    prior=c.get('governance-bootstrap-completed')
    if prior:
        if prior['proposal_sha256']!=digest(p):raise PermissionError('one-time bootstrap already consumed')
        return prior
    pr=api(f"pulls/{pub['pr']}")
    if pr['head']['sha']!=pub['head'] or pr['base']['ref']!='release/v0.1' or pr['head']['repo']['full_name']!=REPO or (not pr['merged'] and pr['base']['sha']!=p['head']):raise PermissionError('bootstrap exact head/base scope')
    changes=api(f"pulls/{pub['pr']}/files?per_page=100")
    if len(changes)!=pr['changed_files'] or {f['filename'] for f in changes}!=set(p['changes']):raise PermissionError('governance-only exact diff required')
    if any(c.content(n,pub['head'])!=value for n,value in p['changes'].items()):raise PermissionError('published content differs from approved proposal')
    runs=api('actions/runs?head_sha='+pub['head'])['workflow_runs']
    manual=next(iter(sorted((r for r in runs if r['name']=='quality-gates' and r['event']=='workflow_dispatch'),key=lambda r:r['id'],reverse=True)),None)
    regular=next(iter(sorted((r for r in runs if r['name']=='quality-gates' and r['event']=='pull_request'),key=lambda r:r['id'],reverse=True)),None)
    if not manual or manual['head_sha']!=pub['head'] or manual['status']!='completed' or manual['conclusion']!='success':raise PermissionError('all real non-bootstrap gates must pass at exact SHA')
    jobs=api(f"actions/runs/{manual['id']}/jobs")['jobs']
    if not jobs or any(j['conclusion']!='success' for j in jobs):raise PermissionError('manual job not successful')
    for required in ('Testar o próprio guard','Executar verificações do projeto'):
        if not any(s['name']==required and s['conclusion']=='success' for j in jobs for s in j['steps']):raise PermissionError('required actual step absent: '+required)
    if not regular or regular['status']!='completed' or regular['conclusion']!='failure':raise PermissionError('expected narrowly scoped old self-guard result required')
    failed=api(f"actions/runs/{regular['id']}/jobs")['jobs']
    steps=[s['name'] for j in failed for s in j['steps'] if s['conclusion']=='failure']
    if steps!=['Proteger testes existentes']:raise PermissionError('bootstrap exception does not cover other failures')
    log=c.failure_log(regular['id'])
    if 'proteção de governança alterada no mesmo PR de produto: scripts/ci/test-integrity-guard.sh' not in log:raise PermissionError('expected old guard evidence missing')
    key=c.root/'signing/test-maintenance-private.pem'
    public=subprocess.run(['openssl','pkey','-in',str(key),'-pubout'],capture_output=True,check=True).stdout.decode()
    if p['changes']['scripts/ci/test-maintenance-public.pem']!=public:raise PermissionError('published trust key mismatch')
    receipt=dict(task=task,proposal_sha256=digest(p),review=v,head=pub['head'],base=p['head'],pr=pub['pr'],ci=manual['id'],old_guard_run=regular['id'],old_guard_log_sha256=hashlib.sha256(log.encode()).hexdigest(),
        exception='CEO-authorized one-time governance self-protection bootstrap only; no product/test/security/branch-protection waiver',authorization='2026-09-20 explicit user approval of guard bootstrap exception and signed maintenance activation')
    intent=c.get('governance-bootstrap-intent')
    if intent and intent!=receipt:raise PermissionError('conflicting bootstrap intent')
    c.put('governance-bootstrap-intent',receipt)
    if not pr['merged']:
        api(f"issues/{pub['pr']}/comments",'POST',dict(body='One-time governance bootstrap authorized by CEO. Exact immutable review: '+task+' / '+digest(p)+'. All other gates executed successfully in run '+str(manual['id'])+'. The old self-protection failure remains recorded in run '+str(regular['id'])+'; it is not changed to green. No product test, security or branch protection is waived.'))
        api('statuses/'+pub['head'],'POST',dict(state='success',context='hermes-independent-review',description=v['reviewer']+': '+task+', exact governance approval'))
        result=api(f"pulls/{pub['pr']}/merge",'PUT',dict(sha=pub['head'],merge_method='merge'))
        if not result.get('merged'):raise PermissionError('GitHub refused normal merge; branch protections unchanged')
        pr=api(f"pulls/{pub['pr']}")
    commit=api('git/commits/'+pr['merge_commit_sha'])
    if [q['sha'] for q in commit['parents']]!=[p['head'],pub['head']]:raise PermissionError('unexpected merge parents')
    receipt['merge']=pr['merge_commit_sha'];c.put('governance-bootstrap-completed',receipt)
    cfg=json.loads((c.root/'config.json').read_text());cfg['signed_test_maintenance']=True
    atomic(c.root/'config.json',cfg);atomic(c.board/'product-adapter.json',cfg)
    return receipt
if __name__=='__main__':
    import sys
    r=finalize(Coordinator(),sys.argv[1]);print(json.dumps({k:r[k] for k in ('task','pr','head','merge','ci','exception')}))
