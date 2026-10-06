"""Operator gate: independent durable verdict plus fresh exact-head CI."""
import json,subprocess
from publish_product_node_trial import api
from publish_lobby_release_base import ROOT,MAIN,OLD

def main():
    code="""import sqlite3,json
from product_workspace import digest
c=sqlite3.connect('/control/controller.db');b=sqlite3.connect('/board/kanban.db')
raw,state=c.execute("select envelope,state from product_pr_verdicts where task='t_59695868' and run=5").fetchone()
v=json.loads(raw)
assert state=='DELIVERED' and v['decision']=='approve' and v['reviewer']=='cto' and v['author']=='techlead'
assert b.execute("select status from tasks where id=?",(v['task'],)).fetchone()==('done',)
assert b.execute('select outcome,summary from task_runs where id=? and task_id=?',(v['run'],v['task'])).fetchone()==('completed','product-pr-verdict:'+digest(v)+'\\n'+v['reason'])
print(json.dumps(v))
"""
    v=json.loads(subprocess.check_output(['docker','exec','truco-online-lobby-controller','python','-c',code],text=True))
    packet=json.loads((ROOT/'release-base-packet.json').read_text())
    assert v['head']==packet['head'] and v['base']==OLD and v['pr']==22
    pr=api('pulls/22')
    assert pr['head']['sha']==v['head'] and pr['base']['ref']=='release/v0.1'
    assert api('git/ref/heads/main')['object']['sha']==MAIN
    if not pr['merged']:
        assert pr['state']=='open' and pr['base']['sha']==OLD
        assert api('git/ref/heads/release/v0.1')['object']['sha']==OLD
        ci=api('actions/runs/'+str(packet['ci']['id']))
        assert ci['head_sha']==v['head'] and ci['conclusion']=='success' and ci['event']=='pull_request'
        checks=api('commits/'+v['head']+'/check-runs')['check_runs']
        assert checks and all(c['status']=='completed' and c['conclusion'] in ('success','skipped','neutral') for c in checks)
        (ROOT/'release-base-merge-intent.json').write_text(json.dumps(dict(verdict=v,ci=ci['id'],checks=[c['id'] for c in checks]),indent=2)+'\n')
        api('statuses/'+v['head'],'POST',dict(state='success',context='hermes-independent-review',description='CTO: t_59695868 run 5, exact frozen PR approved'))
        fresh=api('pulls/22');assert fresh['head']['sha']==v['head'] and fresh['base']['sha']==OLD
        result=api('pulls/22/merge','PUT',dict(sha=v['head'],merge_method='merge'))
        assert result['merged'],result
        pr=api('pulls/22')
    commit=api('git/commits/'+pr['merge_commit_sha'])
    assert [p['sha'] for p in commit['parents']]==[OLD,v['head']]
    assert commit['tree']['sha']==packet['proof']['tree']
    assert api('git/ref/heads/main')['object']['sha']==MAIN
    receipt=dict(pr=22,merge=pr['merge_commit_sha'],head=v['head'],review_task=v['task'],review_run=v['run'],main_unchanged=True)
    (ROOT/'release-base-merged.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt))
if __name__=='__main__':main()
