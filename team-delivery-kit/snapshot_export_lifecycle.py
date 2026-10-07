"""Grouped, read-only snapshot copy helper with exact-ID retirement.

Never execute delivered code, delete a volume, or repeat uncertain deletion.
Preserve restricted lifecycle evidence before retiring the stopped helper.
"""
import json
from pathlib import Path
import re
import subprocess
import uuid
from docker_grouping import labels,args
from controller_broker_image import installed_image
from release_eval import save_receipt


class Effects:
    def image(self,instance):return installed_image(instance)
    def create(self,name,volume,image,expected):
        command=['docker','create','--name',name,*args('snapshot-export',namespace=expected['delivery-kit.owner']),
                 '--label','delivery-kit.owner='+expected['delivery-kit.owner'],
                 '--label','delivery-kit.export-id='+expected['delivery-kit.export-id'],
                 '--network','none','--read-only','--user','10000:10000','--cap-drop','ALL',
                 '--tmpfs','/opt/data:ro,size=1m,mode=0555',
                 '--security-opt','no-new-privileges','--mount',
                 'type=volume,source='+volume+',target=/delivery,readonly','--entrypoint','/bin/true',image]
        result=subprocess.run(command,capture_output=True,text=True,timeout=30,check=True)
        return result.stdout.strip()
    def inspect(self,name):
        result=subprocess.run(['docker','inspect',name],capture_output=True,text=True,timeout=15)
        if result.returncode:
            if result.returncode==1 and ('No such object:' in result.stderr or 'No such container:' in result.stderr):return None
            raise ValueError('export helper identity unobservable')
        values=json.loads(result.stdout)
        if len(values)!=1:raise ValueError('exact export helper required')
        return values[0]
    def copy(self,identity,target):
        subprocess.run(['docker','cp',identity+':/delivery/.',str(target)],capture_output=True,check=True,timeout=60)
    def remove(self,identity):
        subprocess.run(['docker','rm',identity],capture_output=True,check=True,timeout=15)


def verify(info,expected,image,volume,identity=None):
    if (not info or not re.fullmatch('[a-f0-9]{64}',str(info.get('Id')))
            or identity is not None and info['Id']!=identity or info.get('Image')!=image
            or info.get('State',{}).get('Running') is not False or info['State'].get('Status')!='created'
            or any(info.get('Config',{}).get('Labels',{}).get(k)!=v for k,v in expected.items())
            or info['Config'].get('User')!='10000:10000'
            or info.get('HostConfig',{}).get('NetworkMode')!='none'
            or info['HostConfig'].get('ReadonlyRootfs') is not True
            or info['HostConfig'].get('Tmpfs')!={'/opt/data':'ro,size=1m,mode=0555'}
            or len(info.get('Mounts',[]))!=1 or info['Mounts'][0].get('Name')!=volume
            or info['Mounts'][0].get('Destination')!='/delivery' or info['Mounts'][0].get('RW') is not False):
        raise ValueError('exact owned stopped read-only export helper required')
    return info['Id']


def export(volume,target,private,*,instance='delivery-kit-port2',effects=None):
    if not volume.startswith(instance+'-snapshot-'):raise ValueError('owned snapshot name required')
    private=Path(private);directory=private/'snapshot-exports'
    if private.is_symlink() or not private.is_dir() or directory.is_symlink():raise ValueError('private export evidence required')
    directory.mkdir(mode=0o700,exist_ok=True)
    token=uuid.uuid4().hex;name=instance+'-snapshot-export-'+token
    expected={**labels('snapshot-export',namespace=instance),'delivery-kit.owner':instance,'delivery-kit.export-id':token}
    fx=effects or Effects();image=fx.image(instance)
    if not re.fullmatch('sha256:[a-f0-9]{64}',str(image)):raise ValueError('immutable installed export image required')
    path=directory/(token+'.json')
    state=dict(operation='snapshot_export_lifecycle_v1',stage='create_intent',name=name,volume=volume,image=image,
               labels=expected,release_homologated=False)
    def save(**extra):
        nonlocal state
        state={**state,**extra};save_receipt(path,state);return state
    save()
    try:created=fx.create(name,volume,image,expected)
    except (OSError,subprocess.SubprocessError):created=None  # Lookup the unique intent; never another create.
    identity=verify(fx.inspect(name),expected,image,volume,created or None)
    save(stage='copy_intent',container_id=identity)
    copied=False
    try:
        fx.copy(identity,Path(target));copied=True
    finally:
        save(stage='copied' if copied else 'copy_failed')
        # The volume remains durable and read-only; the helper never ran and
        # therefore has no runtime lease/logs. Archive its identity first.
        verify(fx.inspect(identity),expected,image,volume,identity)
        save(stage='retirement_intent',copy_completed=copied)
        try:fx.remove(identity)
        except (OSError,subprocess.SubprocessError):
            if fx.inspect(identity) is not None:
                save(stage='retirement_unconfirmed');raise ValueError('export helper retirement unconfirmed; no repeated delete')
        save(stage='exported' if copied else 'copy_failed_retired')
    return state
