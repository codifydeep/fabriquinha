"""Freeze GitHub PR21 and its trusted base harness for independent review."""
import base64,json,sqlite3
from pathlib import Path
from publish_product_node_trial import api

ROOT=Path('/private/tmp/hermes-node-pr21-review')
ROOT.mkdir(exist_ok=True)
if (ROOT/'packet.json').exists():raise RuntimeError('review already prepared; preserve existing packet')
pr=api('pulls/21');head=pr['head']['sha'];base=pr['base']['sha']
if pr['merged'] or head!='68c5b2a467caa046c5bbcaba01f374938125b35a' or base!='63db9a7a276a2687e33c3b4107ce4acc46236811':raise ValueError('PR identity changed')
diff=api('pulls/21/files?per_page=100')
if len(diff)!=pr['changed_files']:raise ValueError('incomplete diff')
def content(path,sha):
    from urllib.parse import quote
    result=api('contents/'+quote(path,safe='/')+'?ref='+sha)
    return base64.b64decode(result['content']).decode()
base_paths=['adapter-control/ci.py','adapter-control/expected.json','adapter-control/service.mjs','.github/workflows/adapter-node-trial.yml']
checks=api('commits/'+head+'/check-runs')['check_runs']
run=api('actions/runs/35356998300')
packet=dict(pr=21,url=pr['html_url'],head=head,base=base,diff=diff,
            files={f['filename']:content(f['filename'],head) for f in diff},
            trusted_base={n:content(n,base) for n in base_paths},
            ci=dict(event=run['event'],head_sha=run['head_sha'],conclusion=run['conclusion'],url=run['html_url']),
            checks=[{k:c.get(k) for k in ('id','name','head_sha','status','conclusion')} for c in checks],
            limitations=['Node20 fixture only; not approved Node22 product stack','Snapshot review does not approve CI/harness infrastructure','No merge, deploy, QA or rollback yet'])
(ROOT/'packet.json').write_text(json.dumps(packet,ensure_ascii=False,indent=2))
print(json.dumps(dict(packet=str(ROOT/'packet.json'),head=head,base=base,bytes=(ROOT/'packet.json').stat().st_size)))
