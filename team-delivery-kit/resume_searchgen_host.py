"""Resume the existing SEARCHGEN-1 controller after verified host diagnostics."""
import json
import os
import subprocess
import sys
from pathlib import Path
from evalctl import PRIVATE, PROJECT, verify
from release_eval import save_receipt

ROOT=Path(__file__).resolve().parent
PAYLOAD=dict(issue_id='01a10dcb-3312-722b-a0b6-58f4ec391154',
    source_task='01a10dd9-565f-7b04-a83b-67b77b49f0d3',
    interrupted_task='01a10dcc-f751-7baf-a96b-b2bf5e31eb7e')


def main():
    if PROJECT!='delivery-kit-port2' or verify():
        raise ValueError('healthy isolated port2 required')
    launch=PRIVATE/'portable-supervisor'/'SEARCHGEN-1.host-restart.launch.json'
    if launch.exists():
        prior=json.loads(launch.read_text())
        if prior.get('request')!=PAYLOAD:
            raise ValueError('restart launch identity drift')
        # Only one bounded refresh after the verified transient CTO transition.
        identity=subprocess.run(['ps','-p',str(prior.get('pid',0)),'-o','command='],capture_output=True,text=True)
        if identity.returncode==0 or prior.get('transition_refresh'):
            print(json.dumps(dict(stage='existing_resume_intent_inspect_before_retry',pid=prior.get('pid'))));return
        from portable_delivery import managed_handoff
        from portable_supervisor import read_status, stale_restart_blocker
        context=json.loads((PRIVATE/'portable-context-SEARCHGEN-1.json').read_text())
        status=read_status(PRIVATE/'autonomy-status/SEARCHGEN-1.json','SEARCHGEN-1')
        managed=managed_handoff(context)
        eligible=stale_restart_blocker(status,managed)
        if not eligible and managed and managed.get('state',{}).get('stage')=='test_author_active':
            current=json.loads(managed['state']['data'])
            # CTO correction may already have woken the author before the host
            # supervisor returns; confirm the same durable sponsor, not a reset.
            query='import broker as b,json,sys; from handoffs import load;\nwith b.db() as c:\n r=load(c,sys.argv[1]); print(json.dumps(dict(r) if r else None))'
            raw=subprocess.check_output(['docker','exec','-e','PYTHONPATH=/',PROJECT+'-execution-broker-1',
                'python','-c',query,PAYLOAD['source_task']],text=True)
            sponsor=json.loads(raw);details=json.loads(sponsor['data']) if sponsor else {}
            eligible=(status.get('category')=='technical_decision_required:host_restart_diagnosis_required'
                and current.get('phase')=='test_first' and sponsor
                and sponsor['stage']=='test_first_cto_correction_wait'
                and details.get('host_restart_recovery',{}).get('request')==PAYLOAD
                and details.get('decision',{}).get('action')=='request_correction')
        if not eligible:
            raise ValueError('current durable CTO transition required before supervisor refresh')
    result=subprocess.run(['docker','exec','-i','-e','PYTHONPATH=/',PROJECT+'-execution-broker-1',
        'python','-c','import json,sys,broker as b,host_restart_recovery as r; print(json.dumps(r.register(b,json.load(sys.stdin))))'],
        input=json.dumps(PAYLOAD),capture_output=True,text=True)
    if result.returncode:
        # Registration emits only fixed diagnostics, never credential values.
        raise RuntimeError('recovery registration rejected: '+result.stderr[-1500:])
    receipt=json.loads(result.stdout)
    intent=dict(request=PAYLOAD,stage='launch_intent',recovery=receipt,assisted=True)
    if launch.exists():intent.update(transition_refresh=True,previous_launch=prior)
    save_receipt(launch,intent)
    env=dict(os.environ,DELIVERY_KIT_DELIVERY_CONTRACT=str(ROOT/'projects/descartavel2-searchgen-1.contract.json'),
        DELIVERY_KIT_RUN_SPEC=str(ROOT/'projects/descartavel2-searchgen-1.run.json'),DELIVERY_KIT_TEST_FIRST='1')
    for key in ('DELIVERY_KIT_EXISTING_ISSUE_ID','DELIVERY_KIT_TEST_REVISION_PARENT',
                'DELIVERY_KIT_TEST_REVISION_DEPTH','DELIVERY_KIT_SEQUENCE_PLAN'):
        env.pop(key,None)
    with (launch.parent/'SEARCHGEN-1.host-restart.log').open('a') as log:
        target=[sys.executable,'-u',str(ROOT/'portable_supervisor.py'),'--managed-label','SEARCHGEN-1']
        if intent.get('transition_refresh'):
            # Existing controller lock protects against duplicate execution.
            # Its polling now distinguishes the bounded CTO transition.
            target=[sys.executable,'-u',str(ROOT/'portable_delivery.py')]
        child=subprocess.Popen(target,cwd=ROOT,env=env,stdin=subprocess.DEVNULL,
            stdout=log,stderr=log,start_new_session=True)
    intent.update(stage='supervisor_started',pid=child.pid);save_receipt(launch,intent)
    print(json.dumps(dict(stage=intent['stage'],pid=child.pid,issue_id=PAYLOAD['issue_id'],delivery_approval=False)))


if __name__=='__main__':main()
