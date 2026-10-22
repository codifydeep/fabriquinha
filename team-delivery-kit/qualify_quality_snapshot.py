"""Real local copy/immutability qualification; no native task or model calls.

Synthetic inputs are baked into images. One exactly owned named snapshot volume
is retained for recovery; no volume deletion or global Docker cleanup occurs.
Unknown effects remain inspectable in private intents and must not be repeated.
"""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid
from docker_grouping import args as grouped
from qualify_quality_red_observer import save,command,await_retirement,require_idle

ROOT=Path(__file__).resolve().parent
PROBE=('import json,sys;from pathlib import Path;from r3_snapshot_probe import probe;'
    'print(json.dumps(dict(snapshot=probe(Path("/snapshot"),sys.argv[1]),'
    'uid=Path("/snapshot").stat().st_uid,gid=Path("/snapshot").stat().st_gid)))')


def inspect_image(tag,component):
    if not re.fullmatch('delivery-kit-quality-red-'+component+r':[A-Za-z0-9_.-]{1,64}',tag):
        raise ValueError('fixed local qualified image required')
    info=json.loads(subprocess.check_output(['docker','image','inspect',tag],text=True))[0]
    if (info['Config'].get('Volumes') or info['Config'].get('User')!='10000:10000'
            or info['Config'].get('Labels',{}).get('delivery-kit.component')!='quality-red-'+component):
        raise ValueError('dedicated unprivileged image with no inherited volumes required')
    return info


def qualify(namespace,copy_image,observer_image):
    maintenance,idle=require_idle(namespace)
    copier=inspect_image(copy_image,'copy');observer=inspect_image(observer_image,'observer')
    owner=namespace+'-quality-copy-probe'
    if subprocess.check_output(['docker','ps','-aq','--filter','label=delivery-kit.owner='+owner],text=True).strip():
        raise ValueError('observe unsettled copy probe before another operation')
    state=ROOT/('.local-'+namespace.removeprefix('delivery-kit-'));state.mkdir(mode=0o700,exist_ok=True)
    backups=state/'backups';backups.mkdir(mode=0o700,exist_ok=True)
    for previous in backups.glob('quality-copy-docker-*'):
        if (previous/'operation.json').exists() and not (previous/'result.json').exists():
            raise ValueError('unfinished copy qualification; inspect existing private intent, never repeat')
    operation=str(uuid.uuid4());archive=backups/('quality-copy-docker-'+operation);archive.mkdir(mode=0o700)
    volume=namespace+'-quality-copy-proof-'+operation
    labels={'delivery-kit.owner':owner,'delivery-kit.qualification':operation,
        'com.docker.compose.project':namespace+'-tests','delivery-kit.lifecycle':'snapshot'}
    save(archive/'operation.json',dict(operation=operation,volume=volume,labels=labels,
        copy_image=copier['Id'],observer_image=observer['Id'],maintenance=maintenance,idle=idle,
        native_qualification=False,delivery_approval=False,model_calls=0))
    probe=subprocess.run(['docker','volume','inspect',volume],capture_output=True,text=True)
    if probe.returncode==0:raise ValueError('unexpected preexisting volume; not adopted')
    create=['docker','volume','create','--driver','local']
    for key,value in labels.items():create+=['--label',key+'='+value]
    create+=[volume];save(archive/'volume-create-intent.json',dict(argv=create))
    created=command(create)
    save(archive/'volume-create-result.json',dict(exit_code=created.returncode,stdout=created.stdout,stderr=created.stderr))
    if created.returncode:raise RuntimeError('volume outcome requires observation of the recorded name')
    info=json.loads(subprocess.check_output(['docker','volume','inspect',volume],text=True))[0]
    if info['Name']!=volume or info.get('Labels')!=labels or info.get('Driver')!='local':raise ValueError('volume identity drift')
    save(archive/'volume.json',{k:info.get(k) for k in ('Name','Driver','Scope','CreatedAt','Labels','Options')})
    sys.path.insert(0,str(ROOT/'tests'))
    from test_quality_red_observation import QualityRedObservationTests
    fixture=QualityRedObservationTests();fixture.setUp();results=[]
    try:
        fixture.prepare();expected=fixture.prepared
        for variant in ('valid','changed_product'):
            context=archive/variant;context.mkdir(mode=0o700)
            shutil.copytree(fixture.base,context/'base');shutil.copytree(fixture.work,context/'workspace')
            if variant=='changed_product':(context/'workspace/app.py').write_text('VALUE=1\n')
            # COPY uses only the archived synthetic inputs, never host mounts.
            (context/'Dockerfile').write_text('FROM '+copy_image+'\nCOPY base /base\nCOPY workspace /workspace\n')
            tag='delivery-kit-quality-copy-probe:'+operation[:8]+'-'+variant
            save(context/'build-intent.json',dict(image_tag=tag))
            built=command(['docker','build','--network=none','--pull=false','-t',tag,str(context)])
            save(context/'build.json',dict(exit_code=built.returncode,stdout=built.stdout,stderr=built.stderr))
            if built.returncode:raise RuntimeError('copy probe build failed; inspect archived intent')
            image=json.loads(subprocess.check_output(['docker','image','inspect',tag],text=True))[0]
            if image['Config'].get('Volumes'):raise ValueError('copy probe inherited volumes')
            for trial in (('copy','duplicate') if variant=='valid' else ('changed_product',)):
                name=namespace+'-copy-probe-'+operation[:8]+'-'+trial.replace('_','-')
                args=['docker','run','--rm','--name',name,*grouped('quality-copy-probe',namespace),
                    '--label','delivery-kit.owner='+owner,'--network','none','--read-only','--cap-drop','ALL',
                    '--security-opt','no-new-privileges','--user','10000:10000','--memory','128m','--cpus','0.5',
                    '--pids-limit','16','--tmpfs','/tmp:rw,nosuid,nodev,size=32m,mode=1777',
                    '--mount','type=volume,src='+volume+',dst=/snapshot','--env','TEST_FIRST_RESUME=0',image['Id']]
                save(context/(trial+'-intent.json'),dict(argv=args))
                run=command(args);save(context/(trial+'-result.json'),dict(exit_code=run.returncode,stdout=run.stdout,stderr=run.stderr))
                if trial=='copy':
                    if run.returncode!=0 or json.loads(run.stdout)!=expected:raise ValueError('actual snapshot copy differs from expected bytes')
                else:
                    marker='destination is not empty' if trial=='duplicate' else 'base file changed before Red'
                    if run.returncode==0 or marker not in run.stderr:raise ValueError('negative failed for a different reason')
                await_retirement(name)
                check_name=name+'-readback'
                verify=['docker','run','--rm','--name',check_name,*grouped('quality-copy-probe',namespace),
                    '--label','delivery-kit.owner='+owner,'--network','none','--read-only','--cap-drop','ALL',
                    '--security-opt','no-new-privileges','--user','10000:10000','--memory','128m','--cpus','0.5',
                    '--pids-limit','16','--mount','type=volume,src='+volume+',dst=/snapshot,readonly',
                    '--entrypoint','python',observer['Id'],'-c',PROBE,expected['manifest_sha256']]
                save(context/(trial+'-readback-intent.json'),dict(argv=verify))
                checked=command(verify)
                save(context/(trial+'-readback.json'),dict(exit_code=checked.returncode,stdout=checked.stdout,stderr=checked.stderr))
                if checked.returncode:raise ValueError('actual snapshot integrity check failed')
                proof=json.loads(checked.stdout)
                if (proof['uid'],proof['gid'])!=(10000,10000):raise ValueError('volume owner was not initialized for unprivileged copy')
                await_retirement(check_name)
                results.append(dict(case=trial,exit_code=run.returncode,readback=proof,containers_retired=True))
                print(json.dumps(dict(case=trial,status='passed',delivery_approval=False)),flush=True)
        result=dict(operation='synthetic_snapshot_copy_docker_qualification_v2',results=results,
            snapshot_volume_retained=volume,expected_manifest_sha256=expected['manifest_sha256'],
            copy_image=copier['Id'],observer_image=observer['Id'],archive=str(archive),
            native_qualification=False,model_calls=0,delivery_approval=False)
        save(archive/'result.json',result);return result
    finally:fixture.tmp.cleanup()


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--namespace',required=True);p.add_argument('--copy-image',required=True);p.add_argument('--observer-image',required=True)
    a=p.parse_args();print(json.dumps(qualify(a.namespace,a.copy_image,a.observer_image),sort_keys=True))
