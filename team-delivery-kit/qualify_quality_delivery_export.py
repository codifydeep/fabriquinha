"""Real stopped-helper export on synthetic authority, never native approval.

Requires sealed/drained core. Retains a tiny fixture volume and private evidence;
no model, execution of delivered code, network, credentials or worker socket.
An unfinished operation must be observed before starting another qualification.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import uuid
from docker_grouping import args as grouped
from qualify_quality_red_observer import require_idle,save
import quality_delivery_export as exporter

ROOT=Path(__file__).resolve().parent


def observe_failed_build(namespace,operation):
    """Retire only a proved build failure with no created runtime resources."""
    exporter.require(re.fullmatch(r'delivery-kit-[a-z0-9-]{1,48}',namespace)
        and str(uuid.UUID(operation))==operation)
    archive=ROOT/('.local-'+namespace.removeprefix('delivery-kit-'))/'backups'/('quality-export-docker-'+operation)
    original=json.loads((archive/'operation.json').read_bytes())
    build=json.loads((archive/'build-result.json').read_bytes())
    exporter.require(original['operation']==operation and type(build['exit_code']) is int and build['exit_code']!=0
        and not (archive/'volume-intent.json').exists() and not (archive/'initializer-intent.json').exists()
        and exporter.Effects().inspect(namespace+'-export-fixture-'+operation) is None
        and exporter.Effects().inspect(namespace+'-quality-export-'+operation) is None)
    for argv in (['docker','volume','ls','-q','--filter','name=^'+original['volume']+'$'],
            ['docker','image','ls','-q','--filter','reference='+original['fixture_image']]):
        exporter.require(not subprocess.check_output(argv,text=True,timeout=15).strip())
    result=dict(status='failed',phase='fixture_build',observed_no_runtime_effects=True,
        native_qualification=False,model_calls=0,delivery_approval=False)
    save(archive/'result.json',result);return result


def qualify(namespace,image):
    maintenance,idle=require_idle(namespace)
    if not re.fullmatch(r'delivery-kit-quality-green-job:[A-Za-z0-9_.-]{1,64}',image):
        raise ValueError('exact locally built fixed Green job required')
    fx=exporter.Effects();base=fx.image(image);cfg=base['Config']
    exporter.require(cfg.get('User')=='10000:10000' and not cfg.get('Volumes')
        and cfg.get('Labels',{}).get('delivery-kit.component')=='quality-green-job')
    backups=ROOT/('.local-'+namespace.removeprefix('delivery-kit-'))/'backups'
    for prior in backups.glob('quality-export-docker-*'):
        if not (prior/'result.json').exists():raise ValueError('observe unfinished export qualification first')
    operation=str(uuid.uuid4());task=str(uuid.uuid4());run=str(uuid.uuid4())
    archive=backups/('quality-export-docker-'+operation);archive.mkdir(mode=0o700)
    tag='delivery-kit-quality-export-fixture:'+operation
    volume=namespace+'-quality-delivery-'+task;owner=namespace+'-export-qualification'
    labels={'delivery-kit.owner':owner,'delivery-kit.source-task':task,'delivery-kit.quality-run':run,
        'delivery-kit.lifecycle':'snapshot','com.docker.compose.project':namespace+'-tests',
        'com.docker.compose.volume':'quality-delivery-snapshot'}
    save(archive/'operation.json',dict(operation=operation,task_id=task,fixture_image=tag,volume=volume,
        maintenance=maintenance,idle=idle,native_qualification=False,model_calls=0,delivery_approval=False))
    fixture=archive/'fixture';fixture.mkdir(mode=0o700)
    raw=b'VALUE=1\n';facts={'app.py':dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())}
    manifest=json.dumps(dict(files=facts),sort_keys=True,separators=(',',':')).encode()
    (fixture/'app.py').write_bytes(raw);(fixture/'manifest.json').write_bytes(manifest)
    dockerfile=archive/'Dockerfile'
    # BuildKit interprets a raw sha256 image ID as a registry repository.
    # Use the pre-inspected local tag, then recheck its immutable identity.
    dockerfile.write_text('FROM '+image+'\nCOPY --chown=10000:10000 fixture /fixture\n')
    build=['docker','build','--network','none','--pull=false','--tag',tag,'--file',str(dockerfile),str(archive)]
    save(archive/'build-intent.json',dict(argv=build))
    result=subprocess.run(build,capture_output=True,text=True,timeout=120)
    save(archive/'build-result.json',dict(exit_code=result.returncode,stdout=result.stdout,stderr=result.stderr))
    exporter.require(result.returncode==0 and fx.image(image)['Id']==base['Id'])
    fixture_image=fx.image(tag)['Id']
    exporter.require(not subprocess.check_output(['docker','volume','ls','-q','--filter','name=^'+volume+'$'],text=True).strip())
    create=['docker','volume','create','--driver','local']
    for key,value in labels.items():create+=['--label',key+'='+value]
    create+=[volume];save(archive/'volume-intent.json',dict(argv=create))
    subprocess.run(create,capture_output=True,check=True,timeout=30)
    identity={k:fx.volume(volume)[k] for k in ('Name','Driver','Scope','CreatedAt','Labels')}
    name=namespace+'-export-fixture-'+operation
    init=['docker','create','--name',name,*grouped('quality-export-fixture',namespace),
        '--label','delivery-kit.owner='+owner,'--network','none','--read-only','--user','10000:10000',
        '--cap-drop','ALL','--security-opt','no-new-privileges','--memory','64m','--cpus','0.25','--pids-limit','8',
        '--mount','type=volume,source='+volume+',target=/fixture,readonly','--entrypoint','/bin/true',fixture_image]
    save(archive/'initializer-intent.json',dict(argv=init))
    result=subprocess.run(init,capture_output=True,text=True,check=True,timeout=30)
    cid=result.stdout.strip();actual=fx.inspect(cid)
    exporter.require(re.fullmatch('[a-f0-9]{64}',cid) and actual['Name']=='/'+name
        and actual['State']['Status']=='created' and actual['State']['Running'] is False
        and actual['Config']['Labels']['delivery-kit.owner']==owner and actual['Image']==fixture_image)
    save(archive/'initializer-inspection.json',{k:actual[k] for k in ('Id','Name','Image','State','Mounts')})
    save(archive/'initializer-retirement-intent.json',dict(container_id=cid))
    fx.remove(cid);exporter.require(fx.inspect(cid) is None and fx.inspect(name) is None)
    descriptor=dict(operation='quality_delivery_export_authority_v2',namespace=namespace,owner=owner,
        request_id=operation,task_id=task,issue_id=str(uuid.uuid4()),run_id=run,
        manifest_sha256=hashlib.sha256(manifest).hexdigest(),file_inventory=facts,
        capture_context_sha256='a'*64,capture_state_sha256='b'*64,plan_sha256='c'*64,frozen_sha256='d'*64,
        image=base['Id'],volume_identity=identity)
    save(archive/'synthetic-descriptor.json',descriptor)
    receipt=exporter.export(descriptor,archive,effects=fx)
    exporter.require(exporter.export(descriptor,archive,effects=fx)==receipt
        and (Path(receipt['directory'])/'app.py').read_bytes()==raw)
    final=dict(operation='quality_delivery_export_docker_qualification_v2',status='passed',
        source_authority='synthetic_fixture_not_native',receipt=receipt,retained_volume=volume,
        native_qualification=False,model_calls=0,delivery_approval=False)
    save(archive/'result.json',final)
    return dict(status='passed',archive=str(archive),model_calls=0,native_qualification=False,delivery_approval=False)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--namespace',required=True);parser.add_argument('--image')
    parser.add_argument('--observe-failed-build')
    args=parser.parse_args()
    if args.observe_failed_build:result=observe_failed_build(args.namespace,args.observe_failed_build)
    else:
        if not args.image:parser.error('--image required for a new qualification')
        result=qualify(args.namespace,args.image)
    print(json.dumps(result,sort_keys=True))
