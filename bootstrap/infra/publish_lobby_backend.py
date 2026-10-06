"""Publish exact approved source plus explicit new packaging, without merge."""
import json,subprocess,base64,hashlib
from publish_product_node_trial import api
from publish_lobby_release_base import ROOT

def main():
    packet=json.loads((ROOT/'backend-source-proof.json').read_text())
    base=json.loads((ROOT/'release-base-merged.json').read_text())['merge']
    assert api('git/ref/heads/release/v0.1')['object']['sha']==base
    directory=ROOT/'backend'
    names=['package.json','package-lock.json','tsconfig.json','tsconfig.build.json','eslint.config.mjs','server/app.ts','tests/health.test.ts','tests/regression.test.ts']
    files={n:(directory/n).read_text() for n in names}
    for n,v in packet['files'].items():
        if n!='package.json':assert files[n]==v
    original=base64.b64decode(api('contents/scripts/ci/run-project-checks.sh?ref='+base)['content']).decode()
    start=original.index('  if [[ -f pnpm-lock.yaml ]]');end=original.index('\nfi\n',start)
    node=original[start:end]
    # Existing host path remains intact; Docker fallback executes the same four mandatory gates.
    files['scripts/ci/run-project-checks.sh']=original[:start]+"  if ! command -v node >/dev/null; then\n    bash scripts/ci/node-checks.sh\n  else\n"+node+"\n  fi"+original[end:]
    files['scripts/ci/node-checks.sh']=(directory/'node-checks.sh').read_text()
    evidence=dict(packet)
    for key in ('base_branch','head_branch'):evidence.pop(key,None)
    evidence['packaging_changed']=True
    evidence['pr_approved']=False
    evidence['note']='Source/tests are unchanged from snapshot. Packaging and Docker CI fallback are new operator-authored changes requiring independent CTO review. No homologation.'
    files['docs/evidence/lobby-health-source.json']=json.dumps(evidence,indent=2)+'\n'
    branch='codex/lobby-health-20260918'
    refs=api('git/matching-refs/heads/'+branch)
    exact=[r for r in refs if r['ref']=='refs/heads/'+branch]
    if exact:
        head=exact[0]['object']['sha']
    else:
        tree=api('git/commits/'+base)['tree']['sha']
        tree=api('git/trees','POST',dict(base_tree=tree,tree=[dict(path=n,mode='100755' if n.endswith('.sh') else '100644',type='blob',content=v) for n,v in files.items()]))['sha']
        head=api('git/commits','POST',dict(tree=tree,parents=[base],message='feat: first real Fastify health foundation with immutable TDD evidence and local CI'))['sha']
        api('git/refs','POST',dict(ref='refs/heads/'+branch,sha=head))
    prs=api('pulls?state=all&head=codifydeep:'+branch+'&base=release/v0.1')
    pr=prs[0] if prs else api('pulls','POST',dict(title='Truco lobby: Fastify health foundation + executable local CI',head=branch,base='release/v0.1',body='Real product card t_47a4ef4c. Backend source and both tests preserved exactly from independently approved snapshot '+packet['revision']+'. TDD Red/Green/full-suite durable receipt hashes are in docs/evidence/lobby-health-source.json. New package/lock/type/lint/build configuration and Docker CI fallback were prepared by the operator and require independent CTO review of this exact Git SHA. Test execution has no network, socket or credentials. This is a health foundation only, not a functional lobby or homologation. No merge until exact-head CI and independent PR review.'))
    proof=dict(pr=pr['number'],url=pr['html_url'],head=head,base=base,source_revision=packet['revision'],files_sha256={n:hashlib.sha256(v.encode()).hexdigest() for n,v in files.items()},merged=False)
    (ROOT/'backend-publication.json').write_text(json.dumps(proof,indent=2)+'\n');print(json.dumps(proof))
if __name__=='__main__':main()
