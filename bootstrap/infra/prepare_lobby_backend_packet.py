"""Freeze actual product PR and CI evidence for independent CTO review."""
import base64,json
from publish_product_node_trial import api
from publish_lobby_release_base import ROOT
proof=json.loads((ROOT/'backend-publication.json').read_text())
number=proof['pr'];pr=api('pulls/'+str(number));head=proof['head']
assert pr['head']['sha']==head and pr['base']['sha']==proof['base'] and not pr['merged']
runs=api('actions/runs?head_sha='+head+'&event=pull_request')['workflow_runs']
runs=[r for r in runs if r['name']=='quality-gates']
assert runs,'CI has not started'
run=max(runs,key=lambda r:r['id'])
assert run['status']=='completed' and run['conclusion']=='success','CI not green'
diff=api(f'pulls/{number}/files?per_page=100');assert len(diff)==pr['changed_files']
contents={}
for f in diff:
    name=f['filename']
    assert f['status']!='removed','Unexpected removal'
    if name=='package-lock.json':continue
    contents[name]=base64.b64decode(api('contents/'+name+'?ref='+head)['content']).decode()
packet=dict(pr=number,url=pr['html_url'],head=head,base=proof['base'],
    purpose='First real Fastify health foundation (TDD-01A), not a full lobby: immutable backend app/tests plus operator-authored package/lock/lint/type/build and local Docker CI integration. Assess implementation and added packaging. No product completeness claim.',
    author_provenance='backend_data authored app/test; techlead independently reviewed snapshot. Operator added packaging/CI in technical-coordination role; CTO must independently review the entire Git diff.',
    proof=proof,ci={k:run[k] for k in ('id','event','head_sha','conclusion','html_url')},
    diff=[{k:f.get(k) for k in ('filename','status','sha','additions','deletions')} for f in diff],
    files=contents,lockfile_note='Full package-lock.json is in Git at exact head; its content SHA256 is in proof. CI npm ci and npm audit validate dependency resolution and high/critical advisories.',
    security_findings=['Local npm audit: two moderate advisories in vitest/@vitest/mocker (GHSA-82fw-gwwq-j7x9); no high/critical. CTO must assess whether to require the upstream major upgrade before integration. Test-only dependencies; no dev server exposed. Do not silently waive.'],
    limitations=['Snapshot approval does not approve packaging or Git SHA.','GET /health and unknown-route regression only; session/lobby/web remain later cards.','No merge or homologation is authorized by worker verdict alone.'])
(ROOT/'backend-pr-packet.json').write_text(json.dumps(packet,indent=2)+'\n')
print(json.dumps(dict(pr=number,ci=run['id'],packet='backend-pr-packet.json')))
