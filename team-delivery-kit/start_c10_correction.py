"""One-shot fresh correction dispatch; agents/controller own subsequent handoffs."""
import json
import os
from pathlib import Path
import subprocess
import sys
from evalctl import PRIVATE,PROJECT,verify
from prepare_c10_correction import SHA,LABEL,ROOT
from prepare_issue_base import verified_main
from release_eval import save_receipt
from start_eval import read_model_budget


def main():
    if PROJECT!='delivery-kit-port2' or verify():raise ValueError('healthy isolated port2 required')
    if verified_main()!=SHA:raise ValueError('qualified source moved; replan required')
    context=PRIVATE/('portable-context-'+LABEL+'.json')
    launch=PRIVATE/'portable-supervisor'/(LABEL+'.launch.json')
    if launch.exists():
        prior=json.loads(launch.read_text())
        if prior.get('base_sha')!=SHA:raise ValueError('launch source drift')
        if prior.get('pid'):
            cmd=subprocess.run(['ps','-p',str(prior['pid']),'-o','command='],capture_output=True,text=True)
            if cmd.returncode==0 and str(ROOT/'portable_supervisor.py') in cmd.stdout and LABEL in cmd.stdout:
                print(json.dumps(dict(stage='supervisor_already_running',pid=prior['pid'],label=LABEL)));return
        raise ValueError('existing launch needs evidence reconciliation; do not blindly respawn')
    budget=read_model_budget()
    if budget['remaining']<32:raise ValueError('insufficient authorized reserve')
    env=dict(os.environ,DELIVERY_KIT_DELIVERY_CONTRACT=str(ROOT/'projects/descartavel2-searchgen-1.contract.json'),
        DELIVERY_KIT_RUN_SPEC=str(ROOT/'projects/descartavel2-searchgen-1.run.json'),DELIVERY_KIT_TEST_FIRST='1')
    for key in ('DELIVERY_KIT_EXISTING_ISSUE_ID','DELIVERY_KIT_TEST_REVISION_PARENT',
                'DELIVERY_KIT_TEST_REVISION_DEPTH','DELIVERY_KIT_SEQUENCE_PLAN'):
        env.pop(key,None)
    receipt=dict(label=LABEL,base_sha=SHA,stage='launch_intent',remaining_calls=budget['remaining'])
    save_receipt(launch,receipt)
    if not context.exists():
        result=subprocess.run([sys.executable,str(ROOT/'start_portable.py')],cwd=ROOT,env=env)
        if result.returncode:
            receipt.update(stage='dispatch_blocked',exit_code=result.returncode);save_receipt(launch,receipt)
            raise ValueError('dispatch failed; preserve intent for diagnosis')
    pinned=json.loads(context.read_text())
    if pinned.get('base_sha')!=SHA:raise ValueError('actual prepared base drift')
    with (launch.parent/(LABEL+'.log')).open('a') as log:
        worker=subprocess.Popen([sys.executable,'-u',str(ROOT/'portable_supervisor.py'),'--managed-label',LABEL],
            cwd=ROOT,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
    receipt.update(stage='supervisor_started',pid=worker.pid,issue_id=pinned['issue_id'])
    save_receipt(launch,receipt);print(json.dumps(receipt))


if __name__=='__main__':main()
