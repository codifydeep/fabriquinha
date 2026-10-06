"""Read-only GitHub proof packet for the exact-tree release reconciliation."""
import base64,json
from publish_lobby_release_base import ROOT,MAIN,OLD
from publish_product_node_trial import api

pr=api('pulls/22');head=pr['head']['sha']
proof=json.loads((ROOT/'release-base-publication.json').read_text())
assert head==proof['head'] and pr['base']['sha']==OLD and not pr['merged']
commit=api('git/commits/'+head);canonical=api('git/commits/'+MAIN)
assert commit['tree']['sha']==canonical['tree']['sha']==proof['tree']
assert [p['sha'] for p in commit['parents']]==[OLD,MAIN]
run=api('actions/runs/35371682135')
assert run['head_sha']==head and run['event']=='pull_request' and run['conclusion']=='success'
files=api('pulls/22/files?per_page=100');assert len(files)==pr['changed_files']
def content(name):return base64.b64decode(api('contents/'+name+'?ref='+MAIN)['content']).decode()
packet=dict(pr=22,url=pr['html_url'],head=head,base=OLD,
    purpose='Reconcile stale release with previously independently reviewed main using exactly the same Git tree, preserve both parent histories. No product code yet.',
    author_provenance='Operator performed a mechanical branch reconciliation in engineering-coordination role (techlead); CTO performs independent review. No LLM authorship claimed.',
    authorization='CEO approved controlled restart: old implementation/cards/technical decisions are not obligations; preserve history/backups and use ordinary commits without force push.',
    proof=proof,commit=commit,canonical_main_commit=canonical,
    ci={k:run[k] for k in ('id','event','head_sha','conclusion','html_url')},
    diff=[{k:f.get(k) for k in ('filename','status','sha','additions','deletions')} for f in files],
    reused_approvals={'foundation':14,'planning':19,'reconciliation':20,'canonical_commit':MAIN,
        'rule':'Exact-tree equality is verified mechanically, not inferred from titles. Existing approved artifacts are reused, not claimed newly authored.'},
    audit_files={name:content(name) for name in ('AGENTS.md','docs/governance/inference-policy.md','docs/governance/restart.md',
        'docs/planning/v0.1/approvals.json','scripts/ci/run-project-checks.sh','.github/workflows/quality-gates.yml')},
    limitations=['This review covers mechanical foundation alignment, not the later backend source PR or product CI.',
        'Old attempt documents leave the active tree but remain reachable through the old release parent.',
        'Application checks are not applicable until product code is published; passing governance CI is not app validation.',
        'Main must stay unchanged. Release integration still requires fresh remote SHA/check verification.'])
(ROOT/'release-base-packet.json').write_text(json.dumps(packet,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(dict(packet=str(ROOT/'release-base-packet.json'),bytes=(ROOT/'release-base-packet.json').stat().st_size)))
