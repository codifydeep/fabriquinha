"""Fixed, zero-provider HTTP qualification of bounded model-proxy capacity.

Sealed/idle installation only. An uncertain Docker outcome is observed through
the original handle/output, never replaced by another probe. Private evidence
does not authorize a review retry or change a paid-call ceiling.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import uuid
from docker_grouping import args as grouping
from install_quality_preview import save
from migrate_quality_candidate_pin import read
from qualify_quality_red_observer import require_idle,await_retirement
from quality_git_candidate import require,Pending
from qualify_quality_review_stop import sha

ROOT=Path(__file__).resolve().parent


def volumes():
    return sorted(subprocess.check_output(['docker','volume','ls','-q'],text=True,timeout=15).splitlines())


def validate_report(report,source):
    require(isinstance(report,dict) and report.get('operation')=='real_http_proxy_capacity_canary_v1'
        and report.get('status')=='passed' and report.get('source_sha256')==source
        and report.get('max_request_bytes')==2097152 and type(report.get('max_request_bytes')) is int
        and report.get('fixed_forwards')==2 and report.get('fixture_max_calls')==2 and report.get('fixture_calls')==2
        and report.get('model_calls')==0 and type(report.get('model_calls')) is int
        and report.get('oversized_rejected') is True and report.get('call_ceiling_preserved') is True
        and report.get('counter_preserved') is True and report.get('credentials_mounted') is False
        and report.get('docker_socket') is False and report.get('network')=='none' and report.get('data_tmpfs') is True
        and report.get('tests_approved') is False and report.get('delivery_approval') is False)
    sizes=report.get('accepted_request_bytes')
    require(isinstance(sizes,list) and len(sizes)==2 and all(type(n) is int for n in sizes)
        and 600000<sizes[0]<700000 and 2096128<sizes[1]<=2097152)
    return report


def finish(archive,state):
    identity=state['identity'];output=json.loads(read(archive/'output.json'))
    try:
        require(output['returncode']==0 and require_idle(identity['namespace'])[0]==state['maintenance']
            and sha((ROOT/'model_proxy.py').read_bytes())==identity['source_sha256']
            and sha((ROOT/'tests/model_proxy_capacity_canary.py').read_bytes())==identity['script_sha256'])
        await_retirement(state['container_name'])
        require(volumes()==state['volumes_before'])
        reports=[]
        for line in output['stdout'].splitlines():
            try:value=json.loads(line)
            except ValueError:continue
            if isinstance(value,dict) and value.get('operation')=='real_http_proxy_capacity_canary_v1':reports.append(value)
        require(len(reports)==1);report=validate_report(reports[0],identity['source_sha256'])
    except Exception:
        state['stage']='technical_blocked';save(archive/'state.json',state);raise
    receipt=dict(operation='qualified_model_proxy_capacity_v1',namespace=identity['namespace'],
        qualification_id=identity['operation'],proxy_image=identity['image'],source_sha256=identity['source_sha256'],
        script_sha256=identity['script_sha256'],maintenance_operation=state['maintenance']['operation_id'],
        max_request_bytes=2097152,report=report,output_sha256=sha(output['stdout'].encode()),
        container_retired=True,volumes_created=0,model_calls=0,tests_approved=False,delivery_approval=False)
    state.update(stage='qualified',receipt=receipt);save(archive/'state.json',state);return receipt


def observe(archive,identity):
    state=json.loads(read(archive/'state.json'));require(state['identity']==identity)
    if state['stage']=='qualified':
        receipt=state['receipt'];require(receipt['proxy_image']==identity['image']
            and receipt['qualification_id']==identity['operation'] and receipt['namespace']==identity['namespace']
            and receipt['source_sha256']==identity['source_sha256'] and receipt['script_sha256']==identity['script_sha256']
            and receipt['model_calls']==0 and receipt['delivery_approval'] is False and receipt['container_retired'] is True)
        validate_report(receipt['report'],identity['source_sha256']);return receipt
    if state['stage']=='execution_intent' and (archive/'output.json').exists():return finish(archive,state)
    return dict(stage=state['stage'],qualified=False,model_calls=0,delivery_approval=False,
        next_action='observe original named probe and preserved output; never repeat create/start')


def qualify(namespace,image,operation,*,observe_only=False):
    require(re.fullmatch('delivery-kit-[a-z0-9-]{1,48}',namespace)
        and re.fullmatch('sha256:[a-f0-9]{64}',image) and str(uuid.UUID(operation))==operation)
    script=ROOT/'tests/model_proxy_capacity_canary.py'
    identity=dict(namespace=namespace,image=image,operation=operation,
        source_sha256=sha((ROOT/'model_proxy.py').read_bytes()),script_sha256=sha(script.read_bytes()))
    archive=ROOT/('.local-'+namespace.removeprefix('delivery-kit-'))/'backups'/('model-proxy-capacity-'+operation)
    if archive.exists():return observe(archive,identity)
    require(not observe_only);maintenance,_=require_idle(namespace)
    info=json.loads(subprocess.check_output(['docker','inspect',namespace+'-model-proxy-1'],text=True,timeout=15))[0]
    require(info['Name']=='/'+namespace+'-model-proxy-1' and info['State']['Running'] is False
        and info['Config']['Labels'].get('com.docker.compose.project')==namespace
        and info['Config']['Labels'].get('com.docker.compose.service')=='model-proxy')
    info=json.loads(subprocess.check_output(['docker','image','inspect',image],text=True,timeout=15))[0]
    require(info['Id']==image and info['Config'].get('User')=='10000:10000'
        and info['Config'].get('Volumes') in (None,{}, {'/opt/data':{}})
        and info['Config'].get('Labels',{}).get('delivery-kit.component')=='model-proxy')
    pending=subprocess.check_output(['docker','ps','-aq','--filter',
        'label=delivery-kit.owner='+namespace+'-proxy-capacity'],text=True,timeout=15).strip();require(not pending)
    for previous in archive.parent.glob('model-proxy-capacity-*'):
        require(json.loads(read(previous/'state.json'))['stage'] in ('qualified','technical_blocked'))
    require(archive.parent.resolve()==archive.parent);archive.mkdir(mode=0o700)
    name=namespace+'-proxy-capacity-'+operation
    command=['docker','run','--rm','--name',name,*grouping('proxy-capacity',namespace),
        '--label','delivery-kit.owner='+namespace+'-proxy-capacity','--label','delivery-kit.operation='+operation,
        '--network','none','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges',
        '--memory','128m','--pids-limit','32','--cpus','1','--tmpfs','/tmp:rw,nosuid,nodev,size=32m,mode=1777',
        '--tmpfs','/opt/data:rw,nosuid,nodev,size=1m,mode=1777',
        '--mount','type=bind,source='+str(script)+',target=/probe.py,readonly','--entrypoint','python',image,'/probe.py']
    state=dict(identity=identity,maintenance=maintenance,stage='execution_intent',container_name=name,volumes_before=volumes(),
        command_sha256=sha(json.dumps(command).encode()),model_calls=0,delivery_approval=False)
    save(archive/'state.json',state)
    try:output=subprocess.run(command,capture_output=True,text=True,timeout=60)
    except subprocess.TimeoutExpired:
        state['stage']='outcome_unknown';save(archive/'state.json',state)
        raise Pending('observe original proxy qualification handle; no new probe') from None
    save(archive/'output.json',dict(returncode=output.returncode,stdout=output.stdout,stderr=output.stderr))
    return finish(archive,state)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('namespace','image','operation'):parser.add_argument('--'+key,required=True)
    parser.add_argument('--observe',action='store_true');options=parser.parse_args()
    print(json.dumps(qualify(options.namespace,options.image,options.operation,observe_only=options.observe),sort_keys=True))
