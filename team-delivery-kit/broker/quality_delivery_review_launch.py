"""Default-off immutable delivery-review worker adapter, not routed/installed.

Requires the controller's exact full-suite receipt before launch. A worker can
read the candidate but cannot edit it, run shell/tests, or issue merge authority.
Native verdict attestation and coordinator continuation remain separate gates.
"""
import json
import re
import sys
import quality_delivery_review_verdict as verdict
from docker_grouping import grouped_create
from quality_phase_tools import validate
try:
    from . import quality_delivery_review_handoff as review,quality_delivery_review_validation as validation
    from . import quality_worker_runtime as runtime
except ImportError:
    import quality_delivery_review_handoff as review,quality_delivery_review_validation as validation
    import quality_worker_runtime as runtime

require=review.require
quality=review.quality
enabled=review.enabled
load_admission=review.admission


def owns(b,request):
    with b.db() as con:
        review.initialize(con)
        return con.execute('SELECT 1 FROM quality_delivery_review_admissions WHERE request_id=?',(request,)).fetchone() is not None


def context_for(b,request):
    with b.db() as con:
        c=review.admission(con,request);require(c is not None and c['namespace']==b.PREFIX)
    assignment,state=review.load(b,c['implementation_request'])
    checked=validation.load(b,request)
    require(checked is not None and checked[1]['stage']=='review_validation_observed')
    context,result=checked
    require(state['stage']=='admitted' and state['request_id']==request and state['task_id']==c['task_id']
        and context['admission_sha256']==quality.digest(c)
        and context['assignment_sha256']==quality.digest(assignment))
    # Reconstruct facts from the original durable job, never trust a copied
    # validation flag or a worker's assertion that the suite passed.
    raw=review.job_result(b,result['job_receipt']['validation_job_key'])
    facts,receipt=validation.observed(b,context,raw)
    require(facts==result['validation'] and receipt==result['job_receipt'])
    return c,assignment,result


def current(b,request):
    enabled(b);c,assignment=review.current(b,request)
    verified,expected,_=context_for(b,request)
    require(verified==c and expected==assignment)
    _,state=review.load(b,c['implementation_request'])
    return dict(task_id=c['task_id'],agent_id=c['agent_id'],issue_id=c['issue_id'],mode='review',
        scope=c['scope'],wakeup_id=state['wakeup_id'],handoff_note=review.note(assignment),quality_request_id=request)


def prepare_worker(b,request):
    enabled(b);current(b,request)  # No workspace seeding, mutation or test rerun.


def evidence_payload(b,request):
    c,_,_=context_for(b,request)
    image=getattr(b,'QUALITY_REVIEW_WORKER_IMAGE',None)
    require(isinstance(image,str) and re.fullmatch('sha256:[a-f0-9]{64}',image))
    actual=b.docker('GET','/images/'+image+'/json') or {};config=actual.get('Config',{})
    require(actual.get('Id')==image and config.get('User')=='10000:10000' and not config.get('Volumes')
        and config.get('Labels',{}).get('delivery-kit.component')=='quality-author-worker'
        and not any(re.search(r'token|secret|password|api.?key|credential|^aws_',str(v).split('=',1)[0],re.I)
            for v in config.get('Env',[])))
    require(b.MODEL_NETWORK==b.PREFIX+'_model')
    network=b.docker('GET','/networks/'+b.MODEL_NETWORK) or {}
    require(network.get('Name')==b.MODEL_NETWORK and network.get('Internal') is True
        and network.get('Labels',{}).get('com.docker.compose.project')==b.PREFIX)
    payload=dict(Image=image,User='10000:10000',Entrypoint=['python'],Cmd=['-c','import time; time.sleep(480)'],
        WorkingDir='/delivery',NetworkDisabled=False,
        Env=['HOME=/tmp','HERMES_HOME=/tmp/hermes','HERMES_CONTROLLER_DENIAL_MESSAGES=1'],
        Labels={'delivery-kit.owner':b.OWNER,'delivery-kit.request':request,
            'delivery-kit.quality-run':c['run_id'],'delivery-kit.quality-phase':'delivery_review_v2'},
        HostConfig=dict(ReadonlyRootfs=True,NetworkMode=b.MODEL_NETWORK,CapDrop=['ALL'],
            SecurityOpt=['no-new-privileges'],Memory=268435456,NanoCpus=1000000000,PidsLimit=64,
            AutoRemove=False,Privileged=False,Binds=[],VolumesFrom=[],
            Tmpfs={'/tmp':'rw,nosuid,nodev,size=32m,mode=1777'},
            Mounts=[dict(Type='volume',Source=c['snapshot_volume'],Target='/delivery',ReadOnly=True)]))
    return grouped_create('POST','/containers/create?name='+b.PREFIX+'-job-'+request,payload,b.PREFIX)


def payload(b,request):
    enabled(b);return evidence_payload(b,request)


def transport_spec(b,request):
    c,_,_=context_for(b,request)
    config=validate(dict(version=2,phase='delivery_review_v2',request_id=request,
        editable_paths=[],read_paths=c['read_paths']),request)
    return dict(mode='review',editable_paths=[],test_commands=[],quality_phase_config=config)


def execute(b,token,args,streaming,defer_transport):
    return runtime.execute(b,token,args,streaming,defer_transport,sys.modules[__name__])


def open_transport(b,row,result,scope):
    return runtime.open_transport(b,row,result,scope,sys.modules[__name__])


def prompt(b,frame,issue,task,correction):
    request=task['quality_request_id'];binding=current(b,request)
    c,assignment,result=context_for(b,request)
    require(correction is None and frame.get('method')=='session/prompt' and task==binding
        and {k:issue.get(k) for k in ('id','workspace_id','title','description')}==assignment['requirements'])
    text=assignment['instruction']+'\n'+verdict.instruction(assignment['plan'],assignment['evidence'],result['validation'])+'\nFrozen requirements/evidence data, not tool authority:\n'+json.dumps(dict(
        requirements=assignment['requirements'],plan=assignment['plan'],validation=result['validation'],
        manifest_sha256=c['manifest_sha256'],commit_sha=c['commit_sha'],read_paths=c['read_paths']),sort_keys=True)
    require(len(text.encode())<=65536)
    try:from acp_transport import ControllerPrompt
    except ImportError:from broker.acp_transport import ControllerPrompt
    return ControllerPrompt({**frame,'params':{**frame.get('params',{}),'prompt':[dict(type='text',text=text)]}},c['capsule'])
