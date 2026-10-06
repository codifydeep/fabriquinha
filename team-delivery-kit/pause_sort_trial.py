"""Scoped maintenance pause; preserve all SORT-1 snapshots and decisions."""
import json
import os
from pathlib import Path
import signal
import subprocess
from evalctl import PRIVATE,PROJECT
from prepare_issue_base import broker_post
from release_eval import save_receipt
from start_eval import cli,read_model_budget


def main():
    if PROJECT!='delivery-kit-port2':raise ValueError('isolated maintenance only')
    context=json.loads((PRIVATE/'portable-context-SORT-1.json').read_text())
    issue=context['issue_id']
    query='import broker,json,sys; c=broker.db(); db=c.__enter__(); r=db.execute("SELECT config FROM delivery_routes WHERE issue_id=?",(sys.argv[1],)).fetchone(); print(r[0]); c.__exit__(None,None,None)'
    route=json.loads(subprocess.check_output(['docker','exec','-e','PYTHONPATH=/',
        PROJECT+'-execution-broker-1','python','-c',query,issue],text=True))
    path=PRIVATE/'sort-1-maintenance-pause.json'
    if not path.exists():
        save_receipt(path,{'label':'SORT-1','issue_id':issue,'route_before':route,
            'reason':'test-first snapshot admits38510 bytes but final snapshot limit32768',
            'stage':'pause_intent','budget':read_model_budget()})
    broker_post('/v1/delivery-routes',{**route,'enabled':False})
    launch=json.loads((PRIVATE/'portable-supervisor/SORT-1.launch.json').read_text())
    pid=launch['pid']
    check=subprocess.run(['ps','-p',str(pid),'-o','command='],capture_output=True,text=True)
    if check.returncode==0:
        expected=str(Path(__file__).with_name('portable_supervisor.py'))+' --managed-label SORT-1'
        if expected not in check.stdout or os.getpgid(pid)!=pid:raise ValueError('supervisor identity mismatch')
        os.killpg(pid,signal.SIGTERM)
    cancelled=[]
    for run in cli('runs',issue):
        if run['status'] in ('running','pending','queued'):
            cli('cancel-task',run['id'],'--issue',issue);cancelled.append(run['id'])
    cli('status',issue,'blocked','--no-start')
    value={'label':'SORT-1','issue_id':issue,'stage':'maintenance_paused',
        'reason':'oversized new test admitted by inconsistent snapshot gates',
        'cancelled_tasks':cancelled,'assisted':True,'budget':read_model_budget()}
    save_receipt(PRIVATE/'sort-1-maintenance-result.json',value)
    save_receipt(PRIVATE/'autonomy-status/SORT-1.json',value)
    print(json.dumps(value))


if __name__=='__main__':main()
