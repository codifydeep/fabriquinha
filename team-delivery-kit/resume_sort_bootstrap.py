"""Scoped maintenance resume after a fixed bootstrap probe, never approval."""
import json
import os
import subprocess
import sys
from evalctl import PRIVATE,PROJECT
from prepare_issue_base import broker_post,verified_main
from qa_postmerge_trial import write_once
from start_eval import read_model_budget
from sort_autonomy_trial import BASE,ROOT

PARENT='01a0fa04-0cda-7c8d-8979-78786d61b85f'
CHILD='01a0fa1e-05ca-7bf1-b4e9-423d586d440c'
SOURCE='01a0fa1e-17b4-7376-b700-d454657567bb'
IMAGE='sha256:a2be3720f396d03b7e76e9a2f36c8ac614fa39564600c5a08bfb27925b52338c'
MODE='bootstrap'
COMPLETED_SOURCE=None
TEST_SHA=None
REVIEW_TASK=None
DECISION_TASK=None
CLAIM=None


def main():
    if PROJECT!='delivery-kit-port2':raise ValueError('isolated maintenance only')
    action=sys.argv[1:] or ['child']
    if action not in (['child'],['parent']):raise ValueError('invalid resume action')
    folder=PRIVATE/'portable-supervisor'
    launch=folder/('SORT-1.'+MODE+'-'+action[0]+'.launch.json')
    if launch.exists():return json.loads(launch.read_text())
    if verified_main()!=BASE or read_model_budget()['remaining']<32:
        raise ValueError('unchanged base and bounded model budget required')
    recovery=PRIVATE/'test-revision-recovery'/ (PARENT+'.json')
    intent=json.loads(recovery.read_text())
    if intent.get('child_issue')!=CHILD or intent.get('parent_issue')!=PARENT:
        raise ValueError('same linked child required')
    if action==['child']:
        spec=PRIVATE/'test-revision-recovery'/(intent['label']+'.run.json')
        if MODE=='evidence':
            payload={'issue_id':CHILD,'source_task':SOURCE,'review_task':REVIEW_TASK,
                     'decision_task':DECISION_TASK,'manifest_sha256':TEST_SHA,
                     'claimed_missing_method':CLAIM}
            broker_post('/v1/test-review-evidence-challenge',payload)
        elif MODE=='storage':
            payload={'issue_id':CHILD,'failed_task':SOURCE,'manifest_sha256':TEST_SHA}
            broker_post('/v1/test-review-storage-recovery',payload)
        else:
            payload={'issue_id':CHILD,'source_task':SOURCE,'worker_image':IMAGE}
            if MODE=='format':payload.update(completed_source=COMPLETED_SOURCE,test_sha256=TEST_SHA)
            broker_post('/v1/test-first-'+MODE+'-recovery',payload)
    else:
        from portable_supervisor import STOP,read_status
        progress=read_status(PRIVATE/'autonomy-status'/(intent['label']+'.json'),intent['label'])
        if (not progress or progress.get('issue_id')!=CHILD or progress['stage'] in STOP
                or progress['stage'] not in ('test_first_bootstrap_recovery_pending',
                    'test_first_bootstrap_recovery_wait','waiting_approval',
                    'awaiting_test_revision_review','awaiting_implementation')):
            raise ValueError('actual child controller progress required before parent reconciliation')
        spec=ROOT/'projects/descartavel2-sort-1.run.json'
    write_once(folder/('SORT-1.'+MODE+'-'+action[0]+'.intent.json'),
        {'issue_id':CHILD,'source_task':SOURCE,'image':IMAGE,'assisted':True})
    env={**os.environ,'DELIVERY_KIT_RUN_SPEC':str(spec),'DELIVERY_KIT_TEST_FIRST':'1',
         'DELIVERY_KIT_DELIVERY_CONTRACT':str(ROOT/'projects/descartavel2-sort-1.contract.json')}
    if action==['child']:
        env.update(DELIVERY_KIT_TEST_REVISION_PARENT=PARENT,DELIVERY_KIT_TEST_REVISION_DEPTH='1')
    else:
        env.pop('DELIVERY_KIT_TEST_REVISION_PARENT',None);env['DELIVERY_KIT_TEST_REVISION_DEPTH']='0'
    log=folder/('SORT-1.'+MODE+'-'+action[0]+'.log')
    with log.open('ab') as out:
        process=subprocess.Popen([sys.executable,str(ROOT/'portable_delivery.py')],cwd=ROOT,
            env=env,stdout=out,stderr=subprocess.STDOUT,start_new_session=True)
    value={'stage':'bounded_controller_resume_not_delivered','action':action[0],
           'pid':process.pid,'issue_id':CHILD,'log':str(log),'assisted':True}
    write_once(launch,value);return value


if __name__=='__main__':print(json.dumps(main()))
