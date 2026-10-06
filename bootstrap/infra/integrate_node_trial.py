"""Exact-SHA integration of PR21 after native independent review. No main writes."""
import json,sqlite3
from pathlib import Path
from publish_product_node_trial import api,ROOT
from product_publication import BASE_BRANCH,HEAD_BRANCH

def main():
    review=Path('/private/tmp/hermes-node-pr21-review')
    with sqlite3.connect((review/'verdict.db').as_uri()+'?mode=ro',uri=True) as db:
        verdict=json.loads(db.execute('SELECT verdict FROM verdicts ORDER BY run DESC LIMIT 1').fetchone()[0])
    with sqlite3.connect((review/'board/kanban.db').as_uri()+'?mode=ro',uri=True) as db:
        assert db.execute("SELECT status FROM tasks WHERE id='t_6716d63e'").fetchone()==('done',)
        row=db.execute('SELECT outcome,summary FROM task_runs WHERE id=?',(verdict['run'],)).fetchone()
        assert row[0]=='completed' and json.loads(row[1])==verdict
    assert verdict['decision']=='approve' and verdict['reviewer']=='techlead'
    pr=api('pulls/21')
    assert pr['head']['sha']==verdict['head'] and pr['base']['ref']==BASE_BRANCH and pr['head']['ref']==HEAD_BRANCH
    checks=api('commits/'+verdict['head']+'/check-runs')['check_runs']
    checks=[c for c in checks if c['name']=='adapter-node-contract' and c['app']['slug']=='github-actions' and c['head_sha']==verdict['head']]
    latest=max(checks,key=lambda c:c['id']);assert latest['status']=='completed' and latest['conclusion']=='success'
    ci=api('actions/runs/35356998300');assert ci['head_sha']==verdict['head'] and ci['event']=='pull_request' and ci['conclusion']=='success'
    journal=sqlite3.connect(ROOT/'node-publication.db')
    def put(key,value):
        with journal:journal.execute('INSERT OR IGNORE INTO receipts VALUES(?,?)',(key,json.dumps(value)))
    intent=dict(head=verdict['head'],base=verdict['base'],review_run=verdict['run'],check_id=latest['id'])
    old=journal.execute("SELECT value FROM receipts WHERE key='merge-intent'").fetchone()
    if old:assert json.loads(old[0])==intent
    if not pr['merged']:
        assert pr['base']['sha']==verdict['base'] and pr['state']=='open'
        put('merge-intent',intent)
        result=api('pulls/21/merge','PUT',dict(sha=verdict['head'],merge_method='merge'))
        assert result['merged'];merge=result['sha']
    else:
        assert old,'unexpected external merge';merge=pr['merge_commit_sha']
    commit=api('git/commits/'+merge)
    assert [p['sha'] for p in commit['parents']]==[verdict['base'],verdict['head']]
    proof=dict(merge=merge,**intent,release_homologated=False)
    put('merge',proof);print(json.dumps(proof));journal.close()

if __name__=='__main__':main()
