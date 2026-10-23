"""Real fixed Green job on baked synthetic inputs; no native/Git approval.

Requires idle sealed core, records intents and private evidence, and never
repeats an unknown helper execution. The fixed runner executes the full suite.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid
from docker_grouping import args as grouped
from qualify_quality_red_observer import require_idle,save,command,await_retirement

ROOT=Path(__file__).resolve().parent


def qualify(namespace,image,*,reversion=False):
    maintenance,idle=require_idle(namespace)
    if not re.fullmatch(r'delivery-kit-quality-green-job:[A-Za-z0-9_.-]{1,64}',image):
        raise ValueError('exact fixed Green image required')
    info=json.loads(subprocess.check_output(['docker','image','inspect',image],text=True))[0]
    if (info['Config'].get('User')!='10000:10000' or info['Config'].get('Volumes')
            or info['Config'].get('Labels',{}).get('delivery-kit.component')!='quality-green-job'
            or info['Config'].get('Entrypoint')!=['python','/opt/quality/quality_green_job.py']):
        raise ValueError('dedicated isolated Green runner required')
    if reversion and 'observe_reversion_v2' not in info['Config'].get('Labels',{}).get('delivery-kit.quality-operations','').split(','):
        raise ValueError('image must declare reversion support')
    backups=ROOT/('.local-'+namespace.removeprefix('delivery-kit-'))/'backups'
    for prior in backups.glob('quality-green-docker-*'):
        if not (prior/'result.json').exists():raise ValueError('observe original unfinished Green qualification first')
    operation=str(uuid.uuid4());archive=backups/('quality-green-docker-'+operation);archive.mkdir(mode=0o700)
    name=namespace+'-green-probe-'+operation;tag='delivery-kit-quality-green-probe:'+operation[:8]
    save(archive/'operation.json',dict(operation=operation,image=info['Id'],fixture_image=tag,helper=name,
        maintenance=maintenance,idle=idle,reversion=reversion,native_qualification=False,model_calls=0,delivery_approval=False))
    sys.path.insert(0,str(ROOT/'tests'))
    from test_quality_green_observation import GreenObservationTests
    from broker.quality_lifecycle_v2 import green,qualify_sensitivity
    fixture=GreenObservationTests();fixture.setUp()
    try:
        fixture.prepare_context()
        shutil.copytree(fixture.f.base,archive/'base')
        shutil.copytree(fixture.f.snapshot if reversion else fixture.green,archive/'snapshot')
        if reversion:shutil.copytree(fixture.green,archive/'candidate')
        (archive/'Dockerfile').write_text('FROM '+image+'\nCOPY --chown=10000:10000 base /base\nCOPY --chown=10000:10000 snapshot /snapshot\n'+
            ('COPY --chown=10000:10000 candidate /candidate\n' if reversion else ''))
        build=['docker','build','--network=none','--pull=false','-t',tag,str(archive)]
        save(archive/'build-intent.json',dict(argv=build))
        result=command(build);save(archive/'build-result.json',dict(exit_code=result.returncode,stdout=result.stdout,stderr=result.stderr))
        if result.returncode:raise ValueError('preserve original fixture build result')
        actual=json.loads(subprocess.check_output(['docker','image','inspect',image],text=True))[0]
        if actual['Id']!=info['Id']:raise ValueError('source image tag changed during build')
        candidate=json.loads(subprocess.check_output(['docker','image','inspect',tag],text=True))[0]['Id']
        request=dict(operation='observe_green_v2',plan=fixture.f.plan,task_id=fixture.task,
            base_manifest_sha256=fixture.f.prepared['base_manifest_sha256'],
            snapshot_manifest_sha256=fixture.manifest,green_context=fixture.context)
        if reversion:
            evidence=dict(red=fixture.red,test_review=fixture.review,green=fixture.call()['green'])
            request=dict(operation='observe_reversion_v2',plan=fixture.f.plan,task_id=fixture.task,
                base_manifest_sha256=fixture.f.prepared['base_manifest_sha256'],candidate_manifest_sha256=fixture.manifest,
                reviewed_manifest_sha256=fixture.f.prepared['manifest_sha256'],evidence=evidence)
        args=['docker','run','--rm','--name',name,*grouped('quality-green-probe',namespace),
            '--label','delivery-kit.owner='+namespace+'-quality-green-probe','--network','none','--read-only',
            '--user','10000:10000','--cap-drop','ALL','--security-opt','no-new-privileges',
            '--memory','256m','--cpus','1','--pids-limit','64','--tmpfs','/tmp:rw,nosuid,nodev,size=32m,mode=1777',
            '--env','QUALITY_GREEN_JOB_JSON='+json.dumps(request,sort_keys=True),candidate]
        save(archive/'green-intent.json',dict(argv=args))
        result=command(args);save(archive/'green-result.json',dict(exit_code=result.returncode,stdout=result.stdout,stderr=result.stderr))
        await_retirement(name)
        if result.returncode:raise ValueError('fixed Green failed; preserve result and never rerun this helper')
        report=json.loads(result.stdout)
        if reversion:
            qualify_sensitivity(fixture.f.plan,{**evidence,'sensitivity':report['sensitivity']})
            if (report['operation']!='post_green_reversion_observation_v2' or report['coverage_complete'] is not True
                    or report['missing_criteria']!=[] or report['sensitivity']['controls'][0]['tests_run']!=2
                    or report['snapshot_unchanged'] is not True or report['tests_unchanged'] is not True
                    or report['execution_authorized'] is not False or report['merge_authorized'] is not False
                    or report['delivery_approval'] is not False):raise ValueError('full-suite reversion proof missing')
        else:green(fixture.f.plan,fixture.red,fixture.review,report['green'])
        if not reversion and (report['operation']!='full_suite_green_observation_v2' or report['commit_binding_verified'] is not False
                or report['green']['tests_run']!=2 or report['green']['manifest_sha256']!=fixture.manifest
                or report['green']['commit_sha']!=fixture.context['commit_sha'] or report['snapshot_unchanged'] is not True
                or report['execution_authorized'] is not False or report['delivery_approval'] is not False):
            raise ValueError('exact full-suite synthetic Green proof missing')
        final=dict(operation='quality_reversion_fixed_job_docker_qualification_v2' if reversion else 'quality_green_fixed_job_docker_qualification_v2',status='passed',image=info['Id'],
            report_sha256=hashlib.sha256(result.stdout.encode()).hexdigest(),full_suite_tests=2,helper_retired=True,
            native_qualification=False,git_binding_qualification=False,model_calls=0,delivery_approval=False)
        save(archive/'result.json',final)
        return dict(status='passed',archive=str(archive),native_qualification=False,model_calls=0,delivery_approval=False)
    finally:fixture.doCleanups()


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--namespace',required=True);p.add_argument('--image',required=True)
    p.add_argument('--reversion',action='store_true')
    args=p.parse_args();print(json.dumps(qualify(args.namespace,args.image,reversion=args.reversion),sort_keys=True))
