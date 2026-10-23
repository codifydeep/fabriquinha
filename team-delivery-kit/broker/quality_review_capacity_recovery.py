"""Validate operator-observed transport capacity, never worker retry claims.

The host adapter authenticates private install/source/log archives. This side
rechecks the installed Docker identity, finite profile and packaged source.
Only the existing completion lineage may consume this as changed evidence.
"""
import hashlib
from pathlib import Path
import re
import uuid
from proxy_capacity_contract import require,digest,validate_report,rejection


def source_sha256():
    installed=Path(__file__).with_name('qualified_proxy_source.py')
    path=installed if installed.is_file() else Path(__file__).resolve().parents[1]/'model_proxy.py'
    return hashlib.sha256(path.read_bytes()).hexdigest()


def failure_sha256(task):
    require(task.get('status')=='failed' and task.get('result') is None
        and task.get('failure_reason')=='agent_error.provider_server_error'
        and isinstance(task.get('error'),str) and task['error'].startswith('hermes session/prompt failed:'))
    return digest({k:task.get(k) for k in ('status','result','failure_reason','error')})


def validate(b,value,operation,request):
    require(isinstance(value,dict) and set(value)=={'operation','installation','rejection'}
        and value['operation']=='observed_proxy_capacity_change_v1')
    rejection(value['rejection'],request)
    installed=value['installation'];proof=installed.get('qualification') or {}
    require(installed.get('operation')=='model_proxy_capacity_install_v1' and installed.get('stage')=='installed_stopped'
        and installed.get('namespace')==b.PREFIX and installed.get('maintenance_operation')==operation
        and installed.get('previous_capacity')==524288 and installed.get('max_request_bytes')==2097152
        and installed.get('previous_image')!=installed.get('current_image')
        and installed.get('previous_container')!=installed.get('current_container')
        and installed.get('data_mounts_preserved') is True and installed.get('credentials_mounts_preserved') is True
        and installed.get('other_containers_unchanged') is True and installed.get('maintenance_sealed') is True
        and installed.get('model_calls')==0 and type(installed.get('model_calls')) is int
        and installed.get('delivery_approval') is False and installed.get('source_sha256')==source_sha256())
    require(str(uuid.UUID(installed['install_operation']))==installed['install_operation'])
    for key in ('previous_image','current_image'):require(re.fullmatch('sha256:[a-f0-9]{64}',str(installed.get(key))))
    for key in ('previous_container','current_container','source_sha256','previous_source_sha256','previous_logs_sha256'):
        require(re.fullmatch('[a-f0-9]{64}',str(installed.get(key))))
    counter=installed.get('counter')
    require(isinstance(counter,dict) and set(counter)=={'calls','sha256'}
        and type(counter['calls']) is int and counter['calls']>=0 and re.fullmatch('[a-f0-9]{64}',str(counter['sha256']))
        and type(installed.get('max_calls')) is int and installed['max_calls']>=counter['calls'])
    require(proof.get('operation')=='qualified_model_proxy_capacity_v1' and proof.get('namespace')==b.PREFIX
        and proof.get('maintenance_operation')==operation and proof.get('proxy_image')==installed['current_image']
        and proof.get('source_sha256')==installed['source_sha256'] and proof.get('max_request_bytes')==2097152
        and proof.get('container_retired') is True and proof.get('volumes_created')==0
        and proof.get('model_calls')==0 and type(proof.get('model_calls')) is int
        and proof.get('tests_approved') is False and proof.get('delivery_approval') is False)
    require(str(uuid.UUID(proof['qualification_id']))==proof['qualification_id'])
    validate_report(proof.get('report'),installed['source_sha256'])
    proxy=b.docker('GET','/containers/'+b.PREFIX+'-model-proxy-1/json') or {}
    config=proxy.get('Config') or {};rows=config.get('Env') or [];env=dict(v.split('=',1) for v in rows)
    require(len(rows)==len(env) and proxy.get('Id')==installed['current_container']
        and proxy.get('Image')==installed['current_image'] and proxy.get('Name')=='/'+b.PREFIX+'-model-proxy-1'
        and proxy.get('State',{}).get('Running') is False and config.get('User')=='10000:10000'
        and config.get('Labels',{}).get('com.docker.compose.project')==b.PREFIX
        and config.get('Labels',{}).get('com.docker.compose.service')=='model-proxy'
        and env.get('MODEL_PROXY_MAX_REQUEST_BYTES')=='2097152'
        and env.get('MODEL_PROXY_MAX_CALLS')==str(installed['max_calls'])
        and env.get('MODEL_PROXY_COUNTER_PATH')=='/meter/calls.json'
        and proxy.get('HostConfig',{}).get('ReadonlyRootfs') is True
        and proxy.get('HostConfig',{}).get('Privileged') is False)
    mounts=proxy.get('Mounts') or []
    require(any(m.get('Destination')=='/meter' and m.get('RW') is True for m in mounts)
        and any(m.get('Destination')=='/secret' and m.get('RW') is False for m in mounts)
        and all(m.get('Destination')!='/var/run/docker.sock' for m in mounts))
    image=b.docker('GET','/images/'+installed['current_image']+'/json') or {}
    require(image.get('Id')==installed['current_image'] and image.get('Config',{}).get('User')=='10000:10000'
        and image.get('Config',{}).get('Labels',{}).get('delivery-kit.component')=='model-proxy')
    # IDs of qualification/installation/container incarnations cannot renew a
    # condition. A genuinely different qualified source/profile is required.
    return digest(dict(operation='review_proxy_capacity_condition_v1',source_sha256=installed['source_sha256'],
        previous_capacity=524288,max_request_bytes=2097152,proxy_image=installed['current_image']))
