"""Host-controller export of an authenticated v2 capture, with one helper.

Descriptor must come from quality_delivery_capture.export_descriptor through
the trusted controller boundary, never an agent message. The helper never runs.
No legacy snapshot-prefix relaxation, host mount, credential, socket or network.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import time
from docker_grouping import labels
from portable_contract import safe_path
from r3_snapshot_probe import probe
from quality_git_candidate import journal,save,canonical,Pending,quality,require


def validate(value):
    expected={'operation','namespace','owner','request_id','task_id','issue_id','run_id','manifest_sha256',
        'file_inventory','capture_context_sha256','capture_state_sha256','plan_sha256','frozen_sha256','image','volume_identity'}
    require(isinstance(value,dict) and set(value)==expected and value['operation']=='quality_delivery_export_authority_v2')
    namespace=value['namespace'];require(isinstance(namespace,str) and re.fullmatch('delivery-kit-[a-z0-9-]{1,48}',namespace))
    require(isinstance(value['owner'],str) and re.fullmatch('[A-Za-z0-9_.-]{1,200}',value['owner']))
    for k in ('request_id','task_id','issue_id','run_id'):canonical(value[k])
    for k in ('manifest_sha256','capture_context_sha256','capture_state_sha256','plan_sha256','frozen_sha256'):quality.sha(value[k])
    require(re.fullmatch('sha256:[a-f0-9]{64}',str(value['image'])))
    identity=value['volume_identity'];name=namespace+'-quality-delivery-'+value['task_id']
    require(isinstance(identity,dict) and set(identity)=={'Name','Driver','Scope','CreatedAt','Labels'}
        and identity['Name']==name and identity['Driver']=='local' and identity['Scope']=='local'
        and isinstance(identity['CreatedAt'],str) and 1<=len(identity['CreatedAt'])<=100
        and identity['Labels']=={'delivery-kit.owner':value['owner'],'delivery-kit.source-task':value['task_id'],
            'delivery-kit.quality-run':value['run_id'],'delivery-kit.lifecycle':'snapshot',
            'com.docker.compose.project':namespace+'-tests','com.docker.compose.volume':'quality-delivery-snapshot'})
    facts=value['file_inventory'];require(isinstance(facts,dict) and 1<=len(facts)<=128)
    for path,item in facts.items():
        safe_path(path);require(path!='manifest.json' and isinstance(item,dict) and set(item)=={'bytes','sha256'}
            and type(item['bytes']) is int and 0<=item['bytes']<=2*1024*1024);quality.sha(item['sha256'])
    require(sum(item['bytes'] for item in facts.values())<=16*1024*1024
        and hashlib.sha256(json.dumps(dict(files=facts),sort_keys=True,separators=(',',':')).encode()).hexdigest()==value['manifest_sha256'])
    return value


def payload(d):
    return dict(Image=d['image'],User='10000:10000',Entrypoint=['/bin/true'],Cmd=['quality-delivery-export'],
        Labels={**labels('quality-delivery-export',d['namespace']),'delivery-kit.owner':d['namespace']+'-quality-export-v2',
            'delivery-kit.request':d['request_id'],'delivery-kit.source-task':d['task_id'],
            'delivery-kit.export-manifest':d['manifest_sha256']},
        HostConfig=dict(NetworkMode='none',ReadonlyRootfs=True,CapDrop=['ALL'],SecurityOpt=['no-new-privileges'],
            Memory=67108864,NanoCpus=250000000,PidsLimit=8,Mounts=[
                dict(Type='volume',Source=d['volume_identity']['Name'],Target='/delivery',ReadOnly=True)]))


class Effects:
    def inspect(self,identity):
        result=subprocess.run(['docker','container','inspect',identity],capture_output=True,text=True,timeout=15)
        if result.returncode:
            if result.returncode==1 and 'No such container' in result.stderr:return None
            raise Pending('export helper cannot be observed')
        rows=json.loads(result.stdout);require(len(rows)==1);return rows[0]
    def image(self,identity):
        result=subprocess.run(['docker','image','inspect',identity],capture_output=True,text=True,timeout=15,check=True)
        rows=json.loads(result.stdout);require(len(rows)==1);return rows[0]
    def volume(self,name):
        result=subprocess.run(['docker','volume','inspect',name],capture_output=True,text=True,timeout=15,check=True)
        rows=json.loads(result.stdout);require(len(rows)==1);return rows[0]
    def create(self,name,p):
        args=['docker','create','--name',name,'--network','none','--read-only','--user',p['User'],
            '--cap-drop','ALL','--security-opt','no-new-privileges','--memory','64m','--cpus','0.25','--pids-limit','8']
        for k,v in p['Labels'].items():args+=['--label',k+'='+v]
        args+=['--mount','type=volume,source='+p['HostConfig']['Mounts'][0]['Source']+',target=/delivery,readonly',
            '--entrypoint','/bin/true',p['Image'],*p['Cmd']]
        result=subprocess.run(args,capture_output=True,text=True,timeout=30,check=True)
        return result.stdout.strip()
    def copy(self,identity,target):
        subprocess.run(['docker','cp',identity+':/delivery/.',str(target)],capture_output=True,timeout=60,check=True)
    def remove(self,identity):
        subprocess.run(['docker','rm',identity],capture_output=True,timeout=15,check=True)


def volume(fx,d):
    actual=fx.volume(d['volume_identity']['Name'])
    require(actual is not None and {k:actual.get(k) for k in d['volume_identity']}==d['volume_identity']
        and actual.get('Options') in (None,{}))


def inspect(fx,name,p,identity=None):
    actual=fx.inspect(identity or name);require(actual is not None)
    cfg=actual.get('Config',{});host=actual.get('HostConfig',{});mounts=actual.get('Mounts',[])
    require(re.fullmatch('[a-f0-9]{64}',str(actual.get('Id'))) and (identity is None or actual['Id']==identity)
        and actual.get('Name')=='/'+name and actual.get('Image')==p['Image']
        and actual.get('State',{}).get('Status')=='created' and actual['State'].get('Running') is False
        and all(cfg.get(k)==p[k] for k in ('User','Entrypoint','Cmd'))
        and all(cfg.get('Labels',{}).get(k)==v for k,v in p['Labels'].items())
        and all(host.get(k)==p['HostConfig'][k] for k in ('NetworkMode','ReadonlyRootfs','CapDrop','SecurityOpt','Memory','NanoCpus','PidsLimit'))
        and host.get('Privileged',False) is False and all(host.get(k) in (None,[]) for k in ('Binds','VolumesFrom','CapAdd'))
        and len(mounts)==1 and mounts[0].get('Type')=='volume'
        and mounts[0].get('Name')==p['HostConfig']['Mounts'][0]['Source']
        and mounts[0].get('Destination')=='/delivery' and mounts[0].get('RW') is False)
    return {k:actual[k] for k in ('Id','Name','Image','State','Mounts')}


def verified_files(target,d):
    result=probe(target,d['manifest_sha256'])
    require(json.loads((target/'manifest.json').read_bytes())['files']==d['file_inventory'])
    return result


def export(descriptor,private,*,effects=None):
    d=validate(json.loads(json.dumps(descriptor)));fx=effects or Effects();request=d['request_id']
    name=d['namespace']+'-quality-export-'+request;p=payload(d)
    with journal(private,request,family='quality-delivery-exports') as path:
        target=path.parent/(request+'.files');require(not path.is_symlink() and not target.is_symlink())
        context=dict(descriptor=d,target=str(target),name=name,payload=p)
        if path.exists():
            info=path.stat()
            require(stat.S_ISREG(info.st_mode) and info.st_nlink==1 and info.st_uid==os.getuid() and not info.st_mode&0o077)
            value=json.loads(path.read_bytes());state=value['state']
            require(value['context']==context and value['context_sha256']==quality.digest(context)
                and value['state_sha256']==quality.digest(state)
                and state['stage'] in ('prepared','create_intent','copy_intent','copied','retirement_intent','exported','technical_blocked'))
            if state['stage']=='exported':
                receipt=state['receipt']
                require(receipt==dict(operation='quality_delivery_export_v2',stage='exported',request_id=request,
                    task_id=d['task_id'],descriptor_sha256=quality.digest(d),manifest_sha256=d['manifest_sha256'],
                    directory=str(target),container_id=state['container_id'],helper_retired=True,
                    execution_authorized=False,delivery_approval=False))
                verified_files(target,d);return receipt
            require(state['stage']!='technical_blocked')
        else:
            volume(fx,d);actual=fx.image(d['image']);cfg=actual.get('Config',{})
            require(actual.get('Id')==d['image'] and not cfg.get('Volumes') and cfg.get('User')=='10000:10000'
                and cfg.get('Labels',{}).get('delivery-kit.component')=='quality-green-job'
                and not any(re.search(r'token|secret|password|api.?key|credential|^aws_',str(v).split('=',1)[0],re.I)
                    for v in cfg.get('Env',[])))
            require(not target.exists() and fx.inspect(name) is None)
            state=dict(stage='prepared',deadline=time.time()+600,copy_attempted=False,execution_authorized=False,delivery_approval=False)
            save(path,context,state)
        try:
            if state['stage']=='prepared':
                volume(fx,d);state['stage']='create_intent';save(path,context,state)
                fx.create(name,p)
            if state['stage']=='create_intent':
                if fx.inspect(name) is None:raise Pending('observe original export helper; never recreate')
                info=inspect(fx,name,p)
                state.update(stage='copy_intent',container_id=info['Id'],inspection=info);save(path,context,state)
            if state['stage']=='copy_intent':
                volume(fx,d);inspect(fx,name,p,state['container_id'])
                if not state['copy_attempted']:
                    target.mkdir(mode=0o700,exist_ok=True);require(not any(target.iterdir()))
                    state['copy_attempted']=True;save(path,context,state)
                    fx.copy(state['container_id'],target)
                    report=verified_files(target,d)
                else:
                    try:report=verified_files(target,d)
                    except (ValueError,OSError):raise Pending('observe original copied bytes; never repeat an uncertain transfer') from None
                volume(fx,d)
                for item in target.rglob('*'):
                    if item.is_file():
                        require(item.stat().st_nlink==1 and item.stat().st_uid==os.getuid())
                        item.chmod(0o400)
                        with item.open('rb') as stream:os.fsync(stream.fileno())
                for directory in [p for p in target.rglob('*') if p.is_dir()]+[target]:
                    fd=os.open(directory,os.O_RDONLY)
                    try:os.fsync(fd)
                    finally:os.close(fd)
                state.update(stage='copied',files=report);save(path,context,state)
            if state['stage']=='copied':
                info=inspect(fx,name,p,state['container_id'])
                state.update(stage='retirement_intent',inspection=info);save(path,context,state)
                fx.remove(state['container_id'])
            require(state['stage']=='retirement_intent')
            if fx.inspect(state['container_id']) is not None:
                raise Pending('observe original exact-ID retirement; never repeat remove')
            require(fx.inspect(name) is None)
            verified_files(target,d)
            receipt=dict(operation='quality_delivery_export_v2',stage='exported',request_id=request,task_id=d['task_id'],
                descriptor_sha256=quality.digest(d),manifest_sha256=d['manifest_sha256'],directory=str(target),
                container_id=state['container_id'],helper_retired=True,execution_authorized=False,delivery_approval=False)
            state.update(stage='exported',receipt=receipt);save(path,context,state);return receipt
        except (TimeoutError,subprocess.TimeoutExpired,subprocess.CalledProcessError) as error:
            if time.time()<state['deadline']:raise Pending('observe original export effect and journal; no replay') from error
            state.update(stage='technical_blocked',category='export_observation_deadline',automatic_retry=False)
            save(path,context,state);raise ValueError('export observation blocked; preserve original helper and bytes') from error
        except (ValueError,KeyError,TypeError,OSError) as error:
            state.update(stage='technical_blocked',category=type(error).__name__,automatic_retry=False)
            save(path,context,state);raise ValueError('export identity rejected; preserve original helper and journal') from error
