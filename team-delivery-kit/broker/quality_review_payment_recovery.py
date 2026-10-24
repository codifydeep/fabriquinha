"""Controller checks of host-authenticated payment evidence; no provider calls.

Only operator code reaches this function. Worker tools/endpoints cannot submit
credit claims, clear pauses, mutate budgets or issue review capabilities.
"""
from pathlib import Path
import hashlib
import quality_provider_resolution as contract


def source_sha256():
    installed=Path(__file__).with_name('qualified_proxy_source.py')
    source=installed if installed.is_file() else Path(__file__).resolve().parents[1]/'model_proxy.py'
    return hashlib.sha256(source.read_bytes()).hexdigest()


def validate(b,value,operation,request):
    condition=contract.validate(value,b.PREFIX,operation,request,proxy_source=source_sha256())
    require=contract.require
    proxy=b.docker('GET','/containers/'+b.PREFIX+'-model-proxy-1/json') or {}
    config=proxy.get('Config') or {};rows=config.get('Env') or [];env=dict(v.split('=',1) for v in rows)
    require(len(rows)==len(env) and proxy.get('Id')==value['proxy_container']
        and proxy.get('Image')==value['proxy_image'] and proxy.get('Name')=='/'+b.PREFIX+'-model-proxy-1'
        and proxy.get('State',{}).get('Running') is False and config.get('User')=='10000:10000'
        and config.get('Labels',{}).get('com.docker.compose.project')==b.PREFIX
        and config.get('Labels',{}).get('com.docker.compose.service')=='model-proxy'
        and env.get('MODEL_PROXY_MAX_CALLS')==str(value['max_calls'])
        and env.get('MODEL_PROXY_MAX_REQUEST_BYTES')=='2097152'
        and env.get('MODEL_PROXY_COUNTER_PATH')=='/meter/calls.json'
        and proxy.get('HostConfig',{}).get('ReadonlyRootfs') is True
        and proxy.get('HostConfig',{}).get('Privileged') is False)
    mounts=proxy.get('Mounts') or []
    require(any(m.get('Destination')=='/meter' and m.get('RW') is True for m in mounts)
        and any(m.get('Destination')=='/secret' and m.get('RW') is False for m in mounts)
        and all(m.get('Destination')!='/var/run/docker.sock' for m in mounts))
    image=b.docker('GET','/images/'+value['proxy_image']+'/json') or {}
    require(image.get('Id')==value['proxy_image'] and image.get('Config',{}).get('User')=='10000:10000'
        and image.get('Config',{}).get('Labels',{}).get('delivery-kit.component')=='model-proxy')
    return condition
