"""Real read-only Docker mixed gate canary, never native/team qualification."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import uuid
from docker_grouping import args as grouped
from qualify_quality_red_observer import require_idle,save,await_retirement
from qualify_quality_author_launch import image

ROOT=Path(__file__).resolve().parent


def require(value):
    if not value:raise ValueError('mixed canary evidence incomplete; observe original operation')


def command(args):return subprocess.run(args,capture_output=True,text=True,timeout=180)


def qualify(namespace,red_tag,green_tag):
    maintenance,idle=require_idle(namespace)
    red=image(red_tag,'red-observer');green=image(green_tag,'green-job')
    backups=ROOT/('.local-'+namespace.removeprefix('delivery-kit-'))/'backups'
    fd=os.open(backups/'quality-mixed-qualifier.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    try:
        info=os.fstat(fd);require(stat.S_ISREG(info.st_mode) and info.st_nlink==1 and info.st_uid==os.getuid()
            and not info.st_mode&0o077)
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        return locked(namespace,red_tag,green_tag,red,green,backups,maintenance,idle)
    finally:os.close(fd)


def locked(namespace,red_tag,green_tag,red,green,backups,maintenance,idle):
    for prior in backups.glob('quality-mixed-docker-*'):
        require(not (prior/'operation.json').exists() or (prior/'result.json').exists())
    operation=str(uuid.uuid4());archive=backups/('quality-mixed-docker-'+operation);archive.mkdir(mode=0o700)
    repository=namespace+'-quality-mixed-probe'
    tags=subprocess.check_output(['docker','image','ls',repository,'--format','{{.Tag}}'],text=True).splitlines()
    # Explicit monotonic fixture versions, not Docker list order or opaque UUID age.
    serial=max([int(v) for v in tags if re.fullmatch('[1-9][0-9]{0,17}',v)]+[0])+1
    tag=repository+':'+str(serial);name=namespace+'-mixed-probe-'+operation
    save(archive/'operation.json',dict(operation=operation,helper=name,fixture_tag=tag,namespace=namespace,
        red_image=red['Id'],green_image=green['Id'],maintenance=maintenance,idle=idle,
        native_qualification=False,model_calls=0,delivery_approval=False))
    sys.path.insert(0,str(ROOT/'tests'))
    from test_quality_mixed_observation import MixedObservationTests
    fixture=MixedObservationTests();f=fixture.prepare(test_image=red_tag.split(':')[0]+'@'+red['Id'])
    try:
        shutil.copytree(f.base,archive/'base');shutil.copytree(f.snapshot,archive/'reviewed')
        candidate=archive/'candidate';shutil.copytree(f.snapshot,candidate)
        path=candidate/'app.py';path.chmod(0o600);path.write_bytes(b'VALUE=1\n');path.chmod(0o400)
        manifest=candidate/'manifest.json';facts=json.loads(manifest.read_bytes())
        facts['files']['app.py']=dict(sha256=hashlib.sha256(path.read_bytes()).hexdigest(),bytes=path.stat().st_size)
        manifest.chmod(0o600);manifest.write_bytes(json.dumps(facts,sort_keys=True,separators=(',',':')).encode());manifest.chmod(0o400)
        shutil.copyfile(ROOT/'tests/quality_mixed_runner_canary.py',archive/'canary.py')
        sources={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in (
            'quality_red_observation.py','quality_green_job.py','quality_reversion_job.py',
            'quality_node_baseline.py','quality_node_reporter.mjs','quality_node_evidence.py')}
        sources['quality_lifecycle_v2.py']=hashlib.sha256((ROOT/'broker/quality_lifecycle_v2.py').read_bytes()).hexdigest()
        request=dict(plan=f.plan,task_id=f.task,green_task_id=fixture.green_task,
            base_manifest=f.prepared['base_manifest_sha256'],red_manifest=f.prepared['manifest_sha256'],
            green_manifest=hashlib.sha256(manifest.read_bytes()).hexdigest(),sources=sources)
        save(archive/'request.json',request)
        (archive/'Dockerfile').write_text('FROM '+green_tag+'\nCOPY --chown=10000:10000 base /base\n'
            'COPY --chown=10000:10000 reviewed /reviewed\nCOPY --chown=10000:10000 candidate /snapshot\n'
            'COPY canary.py /opt/quality/quality_mixed_runner_canary.py\n'
            'LABEL delivery-kit.component="quality-mixed-canary"\n'
            'ENTRYPOINT ["python","/opt/quality/quality_mixed_runner_canary.py"]\n')
        argv=['docker','build','--network=none','--pull=false','-t',tag,str(archive)]
        save(archive/'build-intent.json',dict(argv=argv));built=command(argv)
        save(archive/'build-result.json',dict(exit_code=built.returncode,stdout=built.stdout,stderr=built.stderr));require(built.returncode==0)
        current=image(green_tag,'green-job');require(current['Id']==green['Id'])
        actual=json.loads(subprocess.check_output(['docker','image','inspect',tag],text=True))[0]['Id']
        argv=['docker','run','--rm','--name',name,*grouped('quality-mixed-canary',namespace),
            '--label','delivery-kit.owner='+namespace+'-quality-mixed-canary','--network','none','--read-only',
            '--cap-drop','ALL','--security-opt','no-new-privileges','--user','10000:10000',
            '--pids-limit','128','--memory','256m','--cpus','1','--tmpfs','/tmp:rw,nosuid,nodev,size=32m,mode=1777',
            '--env','QUALITY_MIXED_CANARY_JSON='+json.dumps(request,sort_keys=True),actual]
        save(archive/'run-intent.json',dict(argv=argv));result=command(argv)
        save(archive/'run-result.json',dict(exit_code=result.returncode,stdout=result.stdout,stderr=result.stderr))
        await_retirement(name);require(result.returncode==0)
        report=json.loads(result.stdout)
        require(report['operation']=='mixed_executor_docker_canary_v1' and report['status']=='passed'
            and report['node_inventory_frozen'] is True and report['post_green_node_reexecuted'] is True
            and report['source_hashes_verified'] is True and report['green_fixed_job_dispatched'] is True
            and report['native_qualification'] is False and report['model_calls']==0 and report['delivery_approval'] is False)
        final=dict(report=report,helper_retired=True,archive=str(archive),model_calls=0,native_qualification=False,delivery_approval=False)
        save(archive/'result.json',final);return final
    finally:fixture.doCleanups()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('namespace','red-image','green-image'):parser.add_argument('--'+key,required=True)
    args=parser.parse_args();print(json.dumps(qualify(args.namespace,args.red_image,args.green_image),sort_keys=True))
