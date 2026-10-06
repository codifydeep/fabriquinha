"""One maintenance resume into normal CTO-sponsored revision, not approval."""
import json
import os
from pathlib import Path
import subprocess
import sys
from evalctl import PRIVATE,PROJECT
from prepare_issue_base import broker_post,verified_main
from qa_postmerge_trial import write_once
from start_eval import read_model_budget,cli
from sort_autonomy_trial import BASE,ROOT


def main():
    if PROJECT!='delivery-kit-port2':raise ValueError('isolated resume only')
    folder=PRIVATE/'portable-supervisor';launch=folder/'SORT-1.size-recovery.launch.json'
    if launch.exists():
        prior=json.loads(launch.read_text())
        if sys.argv[1:] != ['--reconcile-stale-supervisor']:return prior
        pid=prior['pid']
        if type(pid) is not int or pid<=1:raise ValueError('invalid previous supervisor PID')
        result=subprocess.run(['ps','-p',str(pid),'-o','command='],capture_output=True,text=True)
        if result.returncode==0:raise ValueError('previous PID still exists; do not duplicate supervisor')
        from portable_delivery import read_context,managed_handoff,configure_run
        from portable_contract import from_environment
        from portable_supervisor import stale_size_blocker,read_status
        contract=from_environment();configure_run(contract)
        context=read_context(contract)
        if not stale_size_blocker(read_status(PRIVATE/'autonomy-status/SORT-1.json','SORT-1'),managed_handoff(context)):
            raise ValueError('no evidenced newer CTO handoff for this stale projection')
        restart=folder/'SORT-1.size-recovery.reconcile-launch.json'
        if restart.exists():return json.loads(restart.read_text())
        log=folder/'SORT-1.size-recovery.reconcile.log'
        with log.open('ab') as output:
            process=subprocess.Popen([sys.executable,str(ROOT/'portable_supervisor.py'),'--managed-label','SORT-1'],
                cwd=ROOT,env=os.environ.copy(),stdout=output,stderr=subprocess.STDOUT,start_new_session=True)
        value={'label':'SORT-1','stage':'stale_projection_reconciliation_started','pid':process.pid,
               'previous_pid':pid,'log':str(log),'assisted':True}
        write_once(restart,value);return value
    pause=json.loads((PRIVATE/'sort-1-maintenance-result.json').read_text())
    context=json.loads((PRIVATE/'portable-context-SORT-1.json').read_text())
    if pause['stage']!='maintenance_paused' or pause['issue_id']!=context['issue_id']:
        raise ValueError('exact scoped maintenance pause required')
    if verified_main()!=BASE or read_model_budget()['remaining']<64:
        raise ValueError('same current base and recovery budget required')
    request={'issue_id':context['issue_id'],'source_task':'01a0fa04-1eeb-7224-a293-e2f47f839b36',
        'review_task':'01a0fa07-f64e-72c5-bc71-8cbb9211b29b',
        'manifest_sha256':'00f55606e71a3b60f18342efb4c21dc688458311565de4c6c59b6d9a62579749'}
    broker_post('/v1/test-review-size-recovery',request)
    route=json.loads((PRIVATE/'sort-1-maintenance-pause.json').read_text())['route_before']
    intent=folder/'SORT-1.size-recovery.intent.json'
    if intent.exists():raise ValueError('uncertain resumed launch requires reconciliation')
    write_once(intent,{'label':'SORT-1','request':request,'stage':'resume_intent'})
    broker_post('/v1/delivery-routes',{**route,'enabled':True})
    cli('metadata','set',context['issue_id'],'--key','maintenance_recovery',
        '--value','size_invalidation_cto_revision_required','--type','string')
    env={**os.environ,'DELIVERY_KIT_DELIVERY_CONTRACT':str(ROOT/'projects/descartavel2-sort-1.contract.json'),
        'DELIVERY_KIT_RUN_SPEC':str(ROOT/'projects/descartavel2-sort-1.run.json'),
        'DELIVERY_KIT_TEST_FIRST':'1'}
    log=folder/'SORT-1.size-recovery.log'
    with log.open('ab') as output:
        process=subprocess.Popen([sys.executable,str(ROOT/'portable_supervisor.py'),'--managed-label','SORT-1'],
            cwd=ROOT,env=env,stdout=output,stderr=subprocess.STDOUT,start_new_session=True)
    value={'label':'SORT-1','stage':'recovery_supervisor_started_not_delivered',
        'pid':process.pid,'log':str(log),'assisted':True,'budget':read_model_budget()}
    write_once(launch,value);return value


if __name__=='__main__':print(json.dumps(main()))
