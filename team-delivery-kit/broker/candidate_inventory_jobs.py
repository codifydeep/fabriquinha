"""Durable fixed metadata jobs; no model commands or delivery approval."""
import os
import re
try:
    from . import validation_job
except ImportError:
    import validation_job


def image(b):
    selected=getattr(b,'CANDIDATE_INVENTORY_IMAGE',os.environ.get('BROKER_CANDIDATE_INVENTORY_IMAGE'))
    if not isinstance(selected,str) or not re.fullmatch('sha256:[a-f0-9]{64}',selected):
        raise ValueError('operator-pinned candidate inventory image required')
    return selected


def ensure(b,issue,source,volume):
    selected=image(b)
    labels=(b.docker('GET','/volumes/'+volume) or {}).get('Labels',{})
    if labels.get('delivery-kit.owner')!=b.OWNER or labels.get('delivery-kit.source-task')!=source:
        raise ValueError('owned immutable candidate inventory volume required')
    base=b.handoff_runtime.task_base(b,issue,source)
    payload=dict(Image=selected,User='10000:10000',Entrypoint=['python'],Cmd=['/candidate_inventory.py'],
        NetworkDisabled=True,Env=[],Labels={'delivery-kit.owner':b.OWNER,'delivery-kit.source-task':source},
        HostConfig=dict(ReadonlyRootfs=True,NetworkMode='none',CapDrop=['ALL'],
            SecurityOpt=['no-new-privileges'],Memory=100663296,NanoCpus=500000000,PidsLimit=16,
            Mounts=[dict(Type='volume',Source=volume,Target='/delivery',ReadOnly=True),
                    dict(Type='volume',Source=base['volume'],Target='/base',ReadOnly=True)]))
    result=validation_job.run(b,source,'candidate_inventory',payload)
    if result.get('exit_code')!=0:raise ValueError('fixed candidate inventory failed; preserve executed evidence')
    return selected
