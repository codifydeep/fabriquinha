"""Import an owned never-started image export with verified image metadata.

The private archive is not source code and must never be published. This helper
does not delete the archive, source image or container, and prints no environment.
"""
import argparse
import json
import os
import re
import subprocess


def inspect(kind, name):
    return json.loads(subprocess.check_output(['docker',kind,'inspect',name],text=True))[0]


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source-image',required=True);p.add_argument('--container',required=True)
    p.add_argument('--archive',required=True);p.add_argument('--tag',required=True)
    p.add_argument('--namespace',required=True)
    a=p.parse_args()
    if (not re.fullmatch(r'delivery-kit-[a-z0-9-]+',a.namespace)
            or not re.fullmatch(r'delivery-kit-execution-broker:[a-zA-Z0-9._-]+',a.tag)):
        raise ValueError('fixed controller image family and namespace required')
    source=inspect('image',a.source_image);container=inspect('container',a.container)
    labels=container['Config'].get('Labels',{})
    if (container['Image']!=source['Id'] or container['State']['Status']!='created'
            or not container['State'].get('StartedAt','').startswith('0001-')
            or labels.get('com.docker.compose.project')!=a.namespace+'-tests'
            or labels.get('delivery-kit.owner')!=a.namespace+'-broker-v1'):
        raise ValueError('owned never-started source-image container required')
    if os.path.islink(a.archive) or not os.path.isfile(a.archive):raise ValueError('private export required')
    os.chmod(a.archive,0o600)
    c=source['Config'];changes=[]
    for entry in c.get('Env',[]):
        key,value=entry.split('=',1)
        if re.search(r'TOKEN|SECRET|PASSWORD|API_KEY|CREDENTIAL',key,re.I):
            raise ValueError('credential-bearing image metadata cannot be imported')
        changes+=['--change','ENV '+key+'='+json.dumps(value)]
    for field in ('User','WorkingDir'):
        if c.get(field):changes+=['--change',{'User':'USER','WorkingDir':'WORKDIR'}[field]+' '+c[field]]
    for field in ('Entrypoint','Cmd'):
        if c.get(field) is not None:changes+=['--change',field.upper()+' '+json.dumps(c[field])]
    for key,value in (c.get('Labels') or {}).items():changes+=['--change','LABEL '+key+'='+json.dumps(value)]
    for field,command in (('ExposedPorts','EXPOSE'),('Volumes','VOLUME')):
        for key in (c.get(field) or {}):changes+=['--change',command+' '+key]
    if c.get('Healthcheck') or c.get('OnBuild') or c.get('StopSignal'):
        raise ValueError('unsupported source metadata; retain original image')
    subprocess.run(['docker','import',*changes,a.archive,a.tag],check=True,stdout=subprocess.DEVNULL)
    imported=inspect('image',a.tag)
    for field in ('Env','User','WorkingDir','Entrypoint','Cmd','Labels','ExposedPorts','Volumes'):
        expected=c.get(field);actual=imported['Config'].get(field)
        if (sorted(expected or [])!=sorted(actual or []) if field=='Env' else (expected or None)!=(actual or None)):
            raise ValueError('imported controller metadata drift: '+field)
    print(json.dumps(dict(image_id=imported['Id'],source_image_id=source['Id'],
                         metadata_verified=True,private_archive_retained=True)))


if __name__=='__main__':main()
