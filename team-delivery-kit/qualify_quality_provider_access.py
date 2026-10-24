"""Zero-provider Linux qualification of fixed payment-resolution HTTP/file/locks.

No real credit check, secret, socket, native task, registration, review approval
or deployment qualification. --observe reads the same preserved result only.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import uuid
from docker_grouping import args as grouping
from qualify_quality_red_observer import require_idle,save,await_retirement
from install_quality_preview import save as save_state
from migrate_quality_candidate_pin import read
from quality_provider_resolution import require

ROOT=Path(__file__).resolve().parent
SOURCES={'contract':'quality_provider_resolution.py','resolver':'provider_pause_resolution.py',
    'payment_recovery':'broker/quality_review_payment_recovery.py',
    'lineage':'broker/quality_review_completion_recovery.py','proxy':'model_proxy.py'}


def sha(raw):return hashlib.sha256(raw).hexdigest()


def validate(report,sources):
    expected=dict(operation='fixed_payment_resolution_runtime_canary_v1',status='passed',
        credit_source='fixed_loopback_not_provider',fixture_http_calls=8,model_calls=0,real_provider_calls=0,
        confirmation_required=True,counter_preserved=True,zero_credit_rejected=True,unlimited_key_supported=True,
        readback_no_repeat=True,partial_finish_no_repeat=True,live_lock_observed=True,
        credential_mounts=False,docker_socket=False,image_data_tmpfs=True,
        delivery_approval=False,tests_approved=False,sources=sources)
    require(isinstance(report,dict) and set(report)==set(expected))
    for key,value in expected.items():require(type(report[key]) is type(value) and report[key]==value)
    return report


def finish(directory,state):
    identity=state['identity'];out=json.loads(read(directory/'output.json'))
    require(out['returncode']==0 and require_idle(identity['namespace'])[0]==state['maintenance']
        and identity['sources']=={k:sha((ROOT/p).read_bytes()) for k,p in SOURCES.items()}
        and identity['script_sha256']==sha((ROOT/'tests/quality_provider_resolution_canary.py').read_bytes()))
    await_retirement(state['container'])
    report=validate(json.loads(out['stdout']),identity['sources'])
    receipt=dict(operation='qualified_fixed_payment_runtime_v1',namespace=identity['namespace'],
        qualification_id=identity['operation'],image=identity['image'],report=report,
        maintenance_operation=state['maintenance']['operation_id'],sources=identity['sources'],
        script_sha256=identity['script_sha256'],output_sha256=sha(out['stdout'].encode()),
        command_sha256=state['command_sha256'],
        container_retired=True,model_calls=0,real_provider_calls=0,delivery_approval=False)
    state.update(stage='qualified',receipt=receipt);save_state(directory/'state.json',state);return receipt


def qualify(namespace,image,operation,*,observe=False):
    require(re.fullmatch(r'delivery-kit-[a-z0-9-]{1,48}',namespace) and re.fullmatch('sha256:[a-f0-9]{64}',image)
        and str(uuid.UUID(operation))==operation)
    sources={k:sha((ROOT/p).read_bytes()) for k,p in SOURCES.items()}
    script=ROOT/'tests/quality_provider_resolution_canary.py'
    identity=dict(namespace=namespace,image=image,operation=operation,sources=sources,script_sha256=sha(script.read_bytes()))
    parent=ROOT/('.local-'+namespace.removeprefix('delivery-kit-'))/'backups'
    require(parent.is_dir() and parent.resolve()==parent and not parent.stat().st_mode&0o077)
    directory=parent/('quality-payment-runtime-'+operation)
    if directory.exists():
        state=json.loads(read(directory/'state.json'));require(state['identity']==identity)
        if state['stage']=='qualified':
            receipt=state['receipt'];out=json.loads(read(directory/'output.json'))
            require(receipt['operation']=='qualified_fixed_payment_runtime_v1'
                and receipt['namespace']==namespace and receipt['qualification_id']==operation and receipt['image']==image
                and receipt['sources']==sources and receipt['script_sha256']==identity['script_sha256']
                and receipt['command_sha256']==state['command_sha256'] and out['returncode']==0
                and receipt['output_sha256']==sha(out['stdout'].encode()) and receipt['container_retired'] is True
                and type(receipt['model_calls']) is int and receipt['model_calls']==0
                and type(receipt['real_provider_calls']) is int and receipt['real_provider_calls']==0
                and receipt['delivery_approval'] is False)
            validate(receipt['report'],sources);require(json.loads(out['stdout'])==receipt['report'])
            return receipt
        require(observe)
        if (directory/'output.json').exists():return finish(directory,state)
        return dict(stage='outcome_unknown',model_calls=0,delivery_approval=False,
            next_action='observe original helper/effect; do not repeat run or infer qualification')
    require(not observe)
    maintenance,_=require_idle(namespace)
    paused=subprocess.check_output(['docker','inspect',namespace+'-model-proxy-1','--format','{{.State.Running}}'],text=True,timeout=15)
    require(paused.strip()=='false')
    info=json.loads(subprocess.check_output(['docker','image','inspect',image],text=True,timeout=15))[0]
    require(info['Id']==image and set(info['Config'].get('Volumes') or {})=={'/opt/data'}
        and not any(re.search(r'token|secret|password|api.?key|credential|^aws_',str(v).split('=',1)[0],re.I)
            for v in info['Config'].get('Env',[]))
        and info['Config'].get('Labels',{}).get('delivery-kit.component')=='quality-v2-controller')
    for previous in parent.glob('quality-payment-runtime-*'):
        prior=json.loads(read(previous/'state.json'));require(prior['stage'] in ('qualified','technical_blocked'))
    directory.mkdir(mode=0o700);name=namespace+'-payment-runtime-'+operation
    command=['docker','run','--rm','--name',name,*grouping('payment-runtime-canary',namespace=namespace),
        '--label','delivery-kit.owner='+namespace+'-quality-payment-runtime','--label','delivery-kit.operation='+operation,
        '--network','none','--read-only','--user','10000:10000','--cap-drop','ALL','--security-opt','no-new-privileges',
        '--pids-limit','64','--memory','256m','--cpus','1','--tmpfs','/tmp:rw,nosuid,nodev,size=16m,mode=1777',
        '--tmpfs','/opt/data:rw,nosuid,nodev,size=1m,mode=0700,uid=10000,gid=10000',
        '--mount','type=bind,source='+str(script)+',target=/payment-probe.py,readonly',
        '--env','PYTHONDONTWRITEBYTECODE=1','--entrypoint','python',image,'/payment-probe.py']
    state=dict(identity=identity,stage='execution_intent',maintenance=maintenance,container=name,
        command_sha256=sha(json.dumps(command).encode()),model_calls=0,delivery_approval=False)
    save(directory/'state.json',state)
    try:out=subprocess.run(command,capture_output=True,text=True,timeout=90)
    except subprocess.TimeoutExpired:
        return dict(stage='outcome_unknown',model_calls=0,delivery_approval=False,
            next_action='observe the original helper/effect; never repeat its run')
    save(directory/'output.json',dict(returncode=out.returncode,stdout=out.stdout,stderr=out.stderr))
    if out.returncode!=0:
        await_retirement(name);state['stage']='technical_blocked';save_state(directory/'state.json',state)
        raise ValueError('fixed payment canary failed; private output preserved')
    return finish(directory,state)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('namespace','image','operation'):p.add_argument('--'+key,required=True)
    p.add_argument('--observe',action='store_true');a=p.parse_args()
    print(json.dumps(qualify(a.namespace,a.image,a.operation,observe=a.observe),sort_keys=True))
