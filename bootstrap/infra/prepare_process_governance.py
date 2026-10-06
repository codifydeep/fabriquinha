"""Operator migration preparation. Creates reviewed proposal, never approval."""
import json,os,subprocess,hashlib
from pathlib import Path
from product_autonomy import Coordinator,api
from product_manifest import manifest
from product_workspace import digest

def main():
    c=Coordinator();folder=c.root/'signing';folder.mkdir(mode=0o700,exist_ok=True)
    key=folder/'test-maintenance-private.pem'
    if not key.exists():
        subprocess.run(['openssl','genpkey','-algorithm','ED25519','-out',str(key)],check=True,capture_output=True);key.chmod(0o600)
    public=subprocess.run(['openssl','pkey','-in',str(key),'-pubout'],check=True,capture_output=True).stdout.decode()
    source=Path('/input/governance')
    changes={'AGENTS.md':(source/'AGENTS.md').read_text(),
        'scripts/ci/test-integrity-guard.sh':(source/'test-integrity-guard.sh').read_text(),
        'scripts/ci/verify-test-maintenance.py':(source/'verify-test-maintenance.py').read_text(),
        'scripts/ci/test-maintenance-public.pem':public,
        '.hermes/team/process-policy.json':json.dumps(manifest(),indent=2)+'\n'}
    head=api('git/ref/heads/release/v0.1')['object']['sha']
    changes['docs/governance/company-contract.md']=changes['AGENTS.md']
    generated=json.loads(c.content('.hermes/team/generated-manifest.json',head))
    for path in set(generated['files'])&set(changes):generated['files'][path]=hashlib.sha256(changes[path].encode()).hexdigest()
    changes['.hermes/team/generated-manifest.json']=json.dumps(generated,indent=2)+'\n'
    packet=dict(head=head,allowed_actions=['publish_governance'],changes=changes,files=changes,
        prepared_by='codex_operator',authority='CEO explicitly authorized one governance-only migration on 2026-09-19; never product bypass',
        purpose='Review this exact governance migration. DevOps proposes publication, CTO independently reviews cryptographic provenance and preserved test controls. Specification {}. Proposal does not merge or waive CI.',
        validation='Operator executed isolated guard tests: exact signed maintenance accepted; unsigned assertion edits, ignored tests, modified source and head-key tampering rejected. Reinspect implementation, not this assertion alone.',
        constraints='Only the old self-protection rule may be waived once after independent review. All other CI checks must execute. Do not claim migration or product complete from this proposal. Source was prepared by operator, not authored by the proposing agent.')
    for raw, in c.db.execute("SELECT value FROM records WHERE key LIKE 'governance-publication:%'"):
        old=json.loads(raw)
        if old.get('pr') and old.get('state')=='AWAITING_REAL_CI_AND_SCOPED_BOOTSTRAP':
            current=api(f"pulls/{old['pr']}")
            if current['state']!='open' or current['head']['sha']!=old['head']:continue
            packet['supersedes_publication']={k:old[k] for k in ('pr','head','branch','base')}
            packet['ci_correction']='Real workflow_dispatch exposed generated-contract drift: AGENTS.md must equal docs/governance/company-contract.md and both hashes must match generated-manifest.json. All three are updated together. The checker, model templates and other CI gates remain unchanged.'
    ident='process-governance:'+digest(changes)
    task=c.team_task(ident,packet,'GOVERNANCE — Review process policy and signed test maintenance',author='devops',capability='platform')
    c.put(ident,dict(task=task,head=head,changes_sha256=digest(changes),state='REVIEW_REQUIRED'))
    print(json.dumps(dict(task=task,changes_sha256=digest(changes),private_key_printed=False,approval=False)))
if __name__=='__main__':main()
