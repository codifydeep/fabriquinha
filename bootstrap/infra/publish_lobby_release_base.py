"""Normal-history PR aligning the abandoned release with reviewed main; no merge."""
import json,re,sqlite3
from pathlib import Path
from publish_product_node_trial import api

ROOT=Path(__file__).parents[1]/'product-launch/lobby-publication'
OLD='5884c1e2b0a9950da8f5235e7c03a825efde6014'
MAIN='af8999b849f7c5e43b7c5179073d08c3f34a33bd'
BRANCH='codex/lobby-release-base-20260918'
def main():
    ROOT.mkdir(exist_ok=True)
    journal=sqlite3.connect(ROOT/'publication.db')
    journal.execute('CREATE TABLE IF NOT EXISTS receipts(key TEXT PRIMARY KEY,value TEXT)');journal.commit()
    def durable(key,fn):
        row=journal.execute('SELECT value FROM receipts WHERE key=?',(key,)).fetchone()
        if row:return json.loads(row[0])
        value=fn()
        with journal:journal.execute('INSERT INTO receipts VALUES(?,?)',(key,json.dumps(value)))
        return value
    assert api('git/ref/heads/release/v0.1')['object']['sha']==OLD
    assert api('git/ref/heads/main')['object']['sha']==MAIN
    trees={s:api('git/trees/'+s+'?recursive=1') for s in (OLD,MAIN)}
    assert not any(t['truncated'] for t in trees.values())
    files={s:{f['path']:f for f in t['tree'] if f['type']=='blob'} for s,t in trees.items()}
    protected=[]
    for name,item in files[OLD].items():
        is_test=bool(re.search(r'(^|/)(tests?|specs?|__tests__)/|(^|/)test_[^/]+\.py$|\.(test|spec)\.',name))
        if is_test or name in ('scripts/ci/test-integrity-guard.sh','scripts/ci/test-test-integrity-guard.sh','.github/workflows/quality-gates.yml'):
            assert files[MAIN].get(name,{}).get('sha')==item['sha'], 'baseline test or guard changed: '+name
            protected.append(name)
    main_commit=api('git/commits/'+MAIN)
    head=durable('release-base-head',lambda:api('git/commits','POST',dict(
        message='chore: reconcile release with reviewed restart foundation (preserve both histories)',
        tree=main_commit['tree']['sha'],parents=[OLD,MAIN]))['sha'])
    refs=api('git/matching-refs/heads/'+BRANCH)
    existing=[r for r in refs if r['ref']=='refs/heads/'+BRANCH]
    if existing:assert existing[0]['object']['sha']==head
    else:api('git/refs','POST',dict(ref='refs/heads/'+BRANCH,sha=head))
    def create():
        prs=api('pulls?state=all&head=codifydeep:'+BRANCH+'&base=release/v0.1')
        if prs:return prs[0]
        return api('pulls','POST',dict(title='Truco: reconcile release/v0.1 with approved restart foundation',
            base='release/v0.1',head=BRANCH,body=(
            'Operational prerequisite for the REAL lobby, not another rehearsal.\n\n'
            'release/v0.1 still contained the cancelled attempt and diverged from reviewed main. '
            'This normal-history merge-shaped commit preserves both histories and uses the EXACT tree of main '+MAIN+'. '
            'No force-push, reset, test deletion or guard changes. Old planning documents remain recoverable through Git parents. '
            'Reviewed foundation/planning came from PR14/19/20; this PR still requires its own CI and independent CTO review.\n\n'
            'Logical author role: engineering coordination (operator), reviewer: CTO. No product code or homologation in this PR. '
            'The independently approved backend snapshot t_47a4ef4c will be published separately once this base is integrated.')))
    pr=durable('release-base-pr',create)
    changed=sorted(n for n in set(files[OLD])|set(files[MAIN]) if files[OLD].get(n,{}).get('sha')!=files[MAIN].get(n,{}).get('sha'))
    proof=dict(pr=pr['number'],url=pr['html_url'],head=head,base=OLD,main=MAIN,
        tree=main_commit['tree']['sha'],parents=[OLD,MAIN],protected_unchanged=protected,
        changed=changed,removed=sorted(set(files[OLD])-set(files[MAIN])),merged=False)
    durable('release-base-publication',lambda:proof)
    (ROOT/'release-base-publication.json').write_text(json.dumps(proof,indent=2)+'\n')
    print(json.dumps(proof));journal.close()
if __name__=='__main__':main()
