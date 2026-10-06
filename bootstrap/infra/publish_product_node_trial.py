"""Operator publication of the approved fixture; never merges or approves PRs."""
import hashlib,json,sqlite3,subprocess
from pathlib import Path
from urllib.parse import quote
from product_publication import approved_packet,BASE_BRANCH,HEAD_BRANCH

ROOT=Path('/private/tmp/hermes-product-agent-trial-01')
REPO='codifydeep/truco-online'

def api(path,method='GET',payload=None):
    cmd=['docker','exec','-i','-u','10000','-e','GH_CONFIG_DIR=/opt/data/home/.config/gh','estudo-hermes','gh','api','repos/'+REPO+'/'+path,'--method',method]
    if payload is not None:cmd+=['--input','-']
    result=subprocess.run(cmd,input=json.dumps(payload) if payload is not None else None,capture_output=True,text=True,timeout=45)
    if result.returncode:raise RuntimeError('GitHub request failed: '+str(result.returncode))
    return json.loads(result.stdout) if result.stdout.strip() else {}

def main():
    with sqlite3.connect((ROOT/'control/controller.db').as_uri()+'?mode=ro',uri=True) as private, sqlite3.connect((ROOT/'board/kanban.db').as_uri()+'?mode=ro',uri=True) as native:
        packet=approved_packet(private,native,'product-adapter-agent-trial-01','t_9ad91f7d')
    journal=sqlite3.connect(ROOT/'node-publication.db')
    journal.execute('CREATE TABLE IF NOT EXISTS receipts(key TEXT PRIMARY KEY,value TEXT)');journal.commit()
    def durable(key,fn):
        row=journal.execute('SELECT value FROM receipts WHERE key=?',(key,)).fetchone()
        if row:return json.loads(row[0])
        value=fn()
        with journal:journal.execute('INSERT INTO receipts VALUES(?,?)',(key,json.dumps(value)))
        return value
    source=durable('source-main',lambda:api('git/ref/heads/main')['object']['sha'])
    files={'adapter-node/'+n:v for n,v in packet['files'].items()}
    policy=dict(revision=packet['revision'],image=packet['image'],files={n:hashlib.sha256(v.encode()).hexdigest() for n,v in files.items()})
    workflow='''name: adapter-node-trial
on:
  pull_request:
    branches: ["BASE_BRANCH"]
permissions:
  contents: read
jobs:
  adapter-node-contract:
    if: github.event.pull_request.head.repo.full_name == github.repository && github.event.pull_request.head.ref == 'HEAD_BRANCH'
    runs-on: [self-hosted, linux, arm64, truco-local]
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v5
        with:
          ref: ${{ github.event.pull_request.head.sha }}
          fetch-depth: 0
          persist-credentials: false
      - name: Verify approved snapshot and run isolated Node tests
        env:
          BASE_SHA: ${{ github.event.pull_request.base.sha }}
          HEAD_SHA: ${{ github.event.pull_request.head.sha }}
        run: |
          set -eu
          trusted=$(mktemp "${RUNNER_TEMP}/adapter-ci.XXXXXX.py")
          git show "${BASE_SHA}:adapter-control/ci.py" > "$trusted"
          python3 "$trusted"
'''.replace('BASE_BRANCH',BASE_BRANCH).replace('HEAD_BRANCH',HEAD_BRANCH)
    infrastructure={'adapter-control/ci.py':Path(__file__).with_name('product_node_ci.py').read_text(),
        'adapter-control/expected.json':json.dumps(policy,sort_keys=True),
        'adapter-control/service.mjs':Path(__file__).with_name('product_node_service.mjs').read_text(),
        '.github/workflows/adapter-node-trial.yml':workflow}
    def commit(parent,content,message):
        tree=api('git/commits/'+parent)['tree']['sha']
        tree=api('git/trees','POST',dict(base_tree=tree,tree=[dict(path=n,mode='100644',type='blob',content=v) for n,v in content.items()]))['sha']
        return api('git/commits','POST',dict(message=message,tree=tree,parents=[parent]))['sha']
    base=durable('base-commit',lambda:commit(source,infrastructure,'chore: trusted isolated Node trial harness; no product release'))
    head=durable('head-commit',lambda:commit(base,files,'test: publish exact independently approved Node snapshot'))
    def ensure_ref(branch,sha):
        existing=api('git/matching-refs/heads/'+branch)
        exact=[r for r in existing if r['ref']=='refs/heads/'+branch]
        if exact:
            if exact[0]['object']['sha']!=sha:raise PermissionError('branch changed externally')
        else:api('git/refs','POST',dict(ref='refs/heads/'+branch,sha=sha))
        return sha
    ensure_ref(BASE_BRANCH,base);ensure_ref(HEAD_BRANCH,head)
    def ensure_pr():
        pulls=api('pulls?state=all&head='+quote('codifydeep:'+HEAD_BRANCH,safe='')+'&base='+quote(BASE_BRANCH,safe=''))
        if pulls:return pulls[0]
        return api('pulls','POST',dict(title='ENSAIO Node — entrega imutável e CI local',head=HEAD_BRANCH,base=BASE_BRANCH,
            body='Isolated adapter trial, NOT Truco homologation. Snapshot '+packet['revision']+'. Author backend_data; independent snapshot reviewer techlead, run 5. Snapshot review is NOT approval of this Git SHA. Exact-head PR review and CI are required before merge/deploy. No main changes.'))
    pr=durable('pull-request',ensure_pr)
    if api('git/ref/heads/main')['object']['sha']!=source:raise RuntimeError('main moved externally; inspect before proceeding')
    result=dict(url=pr['html_url'],number=pr['number'],base=base,head=head,revision=packet['revision'],merged=False,pr_approved=False)
    durable('publication',lambda:result);print(json.dumps(result))
    journal.close()

if __name__=='__main__':main()
