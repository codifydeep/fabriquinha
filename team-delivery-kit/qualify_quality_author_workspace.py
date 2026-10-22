"""Real seed/lock filesystem qualification on synthetic inputs, not native work.

Retain two tiny exactly-owned volumes and private evidence for recovery. All
helpers are grouped --rm jobs; uncertain effects are observed, never replayed.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
from types import SimpleNamespace
import uuid
from docker_grouping import args as grouped
from qualify_quality_red_observer import require_idle,save,command,await_retirement
from broker.quality_author_worker import payload

ROOT=Path(__file__).resolve().parent
PROBE='''import hashlib,json,os,subprocess,sys
from pathlib import Path
root=Path('/workspace');result={}
original={p:(root/p).read_bytes() for p in ('app.py','tests/test_old.py')}
(root/'tests/test_new.py').write_text('new test bytes\\n')
result['new_test_write']='allowed'
actions={
 'product_write':lambda:(root/'app.py').write_text('bad'),
 'baseline_write':lambda:(root/'tests/test_old.py').write_text('bad'),
 'undeclared_write':lambda:(root/'tests/rogue.py').write_text('bad'),
 'product_chmod':lambda:os.chmod(root/'app.py',0o666),
 'baseline_unlink':lambda:(root/'tests/test_old.py').unlink(),
 'new_test_rename':lambda:(root/'tests/test_new.py').rename(root/'tests/rogue.py'),
 'symlink':lambda:(root/'tests/rogue.py').symlink_to(root/'app.py'),
}
for key,action in actions.items():
 try:action();raise AssertionError('forbidden action succeeded: '+key)
 except PermissionError:result[key]='denied'
child=subprocess.run([sys.executable,'-c',"from pathlib import Path;Path('/workspace/app.py').write_text('bad')"],capture_output=True)
assert child.returncode!=0 and b'PermissionError' in child.stderr
result['child_process_write']='denied'
assert all((root/p).read_bytes()==data for p,data in original.items())
assert (root/'tests/test_new.py').read_text()=='new test bytes\\n'
result['protected_hashes']={p:hashlib.sha256(data).hexdigest() for p,data in original.items()}
print(json.dumps(result,sort_keys=True))
'''
GREEN_PROBE='''import hashlib,json,os,subprocess,sys
from pathlib import Path
root=Path('/workspace');result={}
protected=('AGENTS.md','tests/test_old.py','tests/test_new.py')
before={p:(root/p).read_bytes() for p in protected}
(root/'app.py').write_text('VALUE=7\\n')
result['product_write']='allowed'
actions={
 'baseline_write':lambda:(root/'tests/test_old.py').write_text('bad'),
 'frozen_new_test_write':lambda:(root/'tests/test_new.py').write_text('bad'),
 'new_test_chmod':lambda:os.chmod(root/'tests/test_new.py',0o666),
 'baseline_chmod':lambda:os.chmod(root/'tests/test_old.py',0o666),
 'baseline_unlink':lambda:(root/'tests/test_old.py').unlink(),
 'new_test_rename':lambda:(root/'tests/test_new.py').rename(root/'tests/rogue.py'),
 'undeclared_write':lambda:(root/'tests/rogue.py').write_text('bad'),
 'symlink':lambda:(root/'tests/rogue.py').symlink_to(root/'app.py'),
}
for key,action in actions.items():
 try:action();raise AssertionError('forbidden action succeeded: '+key)
 except PermissionError:result[key]='denied'
child=subprocess.run([sys.executable,'-c',"from pathlib import Path;Path('/workspace/tests/test_new.py').write_text('bad')"],capture_output=True)
assert child.returncode!=0 and b'PermissionError' in child.stderr
result['child_process_write']='denied'
assert all((root/p).read_bytes()==data for p,data in before.items())
assert (root/'app.py').read_text()=='VALUE=7\\n'
assert not Path('/var/run/docker.sock').exists()
result['protected_hashes']={p:hashlib.sha256(data).hexdigest() for p,data in before.items()}
print(json.dumps(result,sort_keys=True))
'''


def workspace_context(fixture,volumes,phase):
    if phase not in ('tests_only_v2','implementation_v2'):raise ValueError('exact qualification phase required')
    selected=dict(phase=phase,base=dict(volume=volumes['base'],
        manifest_sha256=hashlib.sha256((fixture.base/'manifest.json').read_bytes()).hexdigest()),
        editable_paths=['/workspace/app.py' if phase=='implementation_v2' else '/workspace/tests/test_new.py'])
    if phase=='implementation_v2':
        selected['frozen_seed']=dict(volume=volumes['previous'],
            manifest_sha256=fixture.prepared['manifest_sha256'],test_sha256=fixture.prepared['test_sha256'])
    return dict(source=dict(task_id=fixture.task,run_id='synthetic-qualification',phase=phase),
        volume=volumes['work'],selection=selected)


def fixture_dockerfile(image,green):
    # The real snapshot copier is UID 10000 and creates 0400 files. Preserve
    # that ownership in the baked fixture; default COPY root would model a
    # different, unreadable source. Never relax snapshot access permissions.
    return 'FROM '+image+'\nCOPY base /base\n'+('COPY --chown=10000:10000 previous /previous\n' if green else '')


def observe_failure(namespace,operation):
    """Close only a proved failed probe, never an unknown/missing execution."""
    if (not re.fullmatch(r'delivery-kit-[a-z0-9-]{1,48}',namespace)
            or str(uuid.UUID(operation))!=operation):raise ValueError('exact qualification identity required')
    archive=ROOT/('.local-'+namespace.removeprefix('delivery-kit-'))/'backups'/('quality-author-docker-'+operation)
    original=json.loads((archive/'operation.json').read_text())
    if original['operation']!=operation:raise ValueError('original operation drift')
    phases=original.get('phases') or (('seed','lock','probe','registry') if original.get('worker_image') else ('seed','lock','probe'))
    if original.get('review_canary') and 'review' not in phases:phases+=('review',)
    outcomes=[];failed=None
    for phase in phases:
        result=json.loads((archive/(phase+'-result.json')).read_text())
        intent=json.loads((archive/(phase+'-intent.json')).read_text())
        expected=namespace+'-author-probe-'+operation[:8]+'-'+phase
        if intent['argv'][intent['argv'].index('--name')+1]!=expected:raise ValueError('helper name drift')
        await_retirement(expected)
        outcomes.append(dict(phase=phase,exit_code=result['exit_code'],container_retired=True))
        if type(result['exit_code']) is not int:raise ValueError('actual terminal process result required')
        if result['exit_code']!=0:failed=phase;break
    if failed is None:raise ValueError('no proved failed execution; never close an unknown outcome')
    final=dict(operation='quality_author_filesystem_docker_qualification_v2',status='failed',failed_phase=failed,
        results=outcomes,retained_volumes=original['volumes'],native_qualification=False,model_calls=0,delivery_approval=False)
    save(archive/'result.json',final)
    return final


def qualify(namespace,image,worker_image=None,phase='tests_only_v2'):
    if phase not in ('tests_only_v2','implementation_v2') or (phase=='implementation_v2' and not worker_image):
        raise ValueError('exact phase and Green registry worker required')
    green=phase=='implementation_v2'
    maintenance,idle=require_idle(namespace)
    if not re.fullmatch(r'delivery-kit-quality-author-prep:[A-Za-z0-9_.-]{1,64}',image):raise ValueError('fixed local prep image required')
    info=json.loads(subprocess.check_output(['docker','image','inspect',image],text=True))[0]
    if (info['Config'].get('Volumes') or info['Config'].get('User')!='10000:10000'
            or info['Config'].get('Labels',{}).get('delivery-kit.component')!='quality-author-prep'):
        raise ValueError('dedicated prep image required')
    worker=None
    if worker_image is not None:
        if not re.fullmatch(r'delivery-kit-quality-author-worker:[A-Za-z0-9_.-]{1,64}',worker_image):
            raise ValueError('fixed local worker image required')
        worker=json.loads(subprocess.check_output(['docker','image','inspect',worker_image],text=True))[0]
        if (worker['Config'].get('Volumes') or worker['Config'].get('User')!='10000:10000'
                or worker['Config'].get('Labels',{}).get('delivery-kit.component')!='quality-author-worker'):
            raise ValueError('dedicated worker with no inherited volumes required')
        if green and 'implementation_v2' not in worker['Config'].get('Labels',{}).get('delivery-kit.quality-phases','').split(','):
            raise ValueError('worker does not declare Green handler support')
    owner=namespace+'-quality-author-probe'
    if subprocess.check_output(['docker','ps','-aq','--filter','label=delivery-kit.owner='+owner],text=True).strip():
        raise ValueError('observe previous exact helper before new qualification')
    backups=ROOT/('.local-'+namespace.removeprefix('delivery-kit-'))/'backups'
    for prior in backups.glob('quality-author-docker-*'):
        if (prior/'operation.json').exists() and not (prior/'result.json').exists():
            raise ValueError('unfinished qualification; observe original recorded intents')
    operation=str(uuid.uuid4());archive=backups/('quality-author-docker-'+operation);archive.mkdir(mode=0o700)
    volumes={key:namespace+'-quality-author-'+key+'-'+operation for key in (('base','work','previous') if green else ('base','work'))}
    phases=('seed','lock','probe','registry') if green else (('seed','lock','probe','registry','review') if worker else ('seed','lock','probe'))
    save(archive/'operation.json',dict(operation=operation,volumes=volumes,image=info['Id'],worker_image=worker['Id'] if worker else None,review_canary=worker is not None and not green,phases=phases,phase=phase,maintenance=maintenance,idle=idle,
        native_qualification=False,model_calls=0,delivery_approval=False))
    sys.path.insert(0,str(ROOT/'tests'))
    from test_quality_red_observation import QualityRedObservationTests
    fixture=QualityRedObservationTests();fixture.setUp()
    try:
        fixture.prepare();shutil.copytree(fixture.base,archive/'base')
        if green:shutil.copytree(fixture.snapshot,archive/'previous')
        (archive/'Dockerfile').write_text(fixture_dockerfile(image,green))
        tag='delivery-kit-quality-author-probe:'+operation[:8]
        save(archive/'build-intent.json',dict(image=tag))
        built=command(['docker','build','--network=none','--pull=false','-t',tag,str(archive)])
        save(archive/'build-result.json',dict(exit_code=built.returncode,stdout=built.stdout,stderr=built.stderr))
        if built.returncode:raise RuntimeError('inspect original build result')
        image_id=subprocess.check_output(['docker','image','inspect',tag,'--format','{{.Id}}'],text=True).strip()
        for key,volume in volumes.items():
            observed=subprocess.run(['docker','volume','inspect',volume],capture_output=True)
            if observed.returncode==0:raise ValueError('unexpected preexisting volume; no adoption')
            if b'no such volume' not in observed.stderr.lower():
                raise ValueError('volume observation unknown; do not create or retry')
            args=['docker','volume','create','--driver','local','--label','delivery-kit.owner='+owner,
                '--label','delivery-kit.qualification='+operation,'--label','delivery-kit.lifecycle=qualification-proof',
                '--label','com.docker.compose.project='+namespace+'-tests',volume]
            save(archive/(key+'-volume-intent.json'),dict(argv=args))
            created=command(args);save(archive/(key+'-volume-result.json'),dict(exit_code=created.returncode,stdout=created.stdout,stderr=created.stderr))
            if created.returncode:raise RuntimeError('observe exact named volume; never repeat create')
            actual=json.loads(subprocess.check_output(['docker','volume','inspect',volume],text=True))[0]
            if (actual.get('Name')!=volume or actual.get('Driver')!='local' or actual.get('Scope')!='local'
                    or actual.get('Labels')!={'delivery-kit.owner':owner,'delivery-kit.qualification':operation,
                        'delivery-kit.lifecycle':'qualification-proof','com.docker.compose.project':namespace+'-tests'}):
                raise ValueError('created volume ownership drift; preserve for inspection')
        c=workspace_context(fixture,volumes,phase)
        b=SimpleNamespace(QUALITY_PREP_IMAGE=image_id,OWNER=owner)
        outcomes=[]
        for phase in phases:
            p=payload(b,c,'seed' if phase in ('probe','registry','review') else phase)
            if phase=='probe':p={**p,'Cmd':['-c',GREEN_PROBE if green else PROBE],'Env':[]}
            if green and phase in ('probe','registry'):
                p={**p,'HostConfig':{**p['HostConfig'],'Mounts':[
                    dict(Type='volume',Source=volumes['work'],Target='/workspace')]}}
            if phase=='registry':
                from broker.acp_transport import worker_env
                config=dict(version=2,phase='implementation_v2' if green else 'tests_only_v2',request_id=operation,
                    editable_paths=['/workspace/app.py' if green else '/workspace/tests/test_new.py'],
                    read_paths=['/workspace/tests/test_new.py','/workspace/app.py','/workspace/tests/test_old.py'])
                p={**p,'Cmd':['/quality_implementation_registry_canary.py' if green else '/quality_phase_registry_canary.py'],
                    'Env':worker_env('implementation',False,execution_id=operation,quality_phase_config=config)}
            if phase=='review':
                from broker.acp_transport import worker_env
                config=dict(version=2,phase='test_review_v2',request_id=operation,editable_paths=[],
                    read_paths=['/delivery/app.py','/delivery/tests/test_old.py','/delivery/tests/test_new.py'])
                p={**p,'Cmd':['/quality_review_registry_canary.py'],
                    'Env':worker_env('review',False,execution_id=operation,quality_phase_config=config),
                    'HostConfig':{**p['HostConfig'],'Mounts':[
                        dict(Type='volume',Source=volumes['work'],Target='/delivery',ReadOnly=True)]}}
            name=namespace+'-author-probe-'+operation[:8]+'-'+phase
            args=['docker','run','--rm','--name',name,*grouped('quality-author-probe',namespace),
                '--label','delivery-kit.owner='+owner,'--network','none','--read-only','--cap-drop','ALL',
                '--security-opt','no-new-privileges','--user',p['User'],'--memory','128m','--cpus','0.5','--pids-limit','16',
                '--tmpfs','/tmp:rw,nosuid,nodev,size=32m,mode=1777']
            for cap in p['HostConfig'].get('CapAdd',[]):args+=['--cap-add',cap]
            for mount in p['HostConfig']['Mounts']:
                args+=['--mount','type=volume,src='+mount['Source']+',dst='+mount['Target']+(',readonly' if mount.get('ReadOnly') else '')]
            for env in p['Env']:args+=['--env',env]
            args+=['--entrypoint','python',worker['Id'] if phase in ('registry','review') else image_id,*p['Cmd']]
            save(archive/(phase+'-intent.json'),dict(argv=args))
            executed=command(args)
            save(archive/(phase+'-result.json'),dict(exit_code=executed.returncode,stdout=executed.stdout,stderr=executed.stderr))
            if executed.returncode:
                observe_failure(namespace,operation)
                raise ValueError('qualification failed; inspect recorded '+phase+' result')
            await_retirement(name)
            if phase=='probe':
                report=json.loads(executed.stdout)
                protected={**{p:fixture.old[p] for p in ('AGENTS.md','tests/test_old.py')},'tests/test_new.py':fixture.new} if green else {p:fixture.old[p] for p in ('app.py','tests/test_old.py')}
                expected={p:hashlib.sha256(data).hexdigest() for p,data in protected.items()}
                if report.get('protected_hashes')!=expected:raise ValueError('protected bytes changed')
            if green and phase=='registry':
                report=json.loads(executed.stdout)
                expected={'/workspace/'+p:h for p,h in expected.items()}
                if (report.get('operation')!='implementation_actual_registry_qualification_v2'
                        or report.get('status')!='passed' or report.get('direct_handler_denied') is not True
                        or report.get('product_write') is not True or report.get('frozen_tests_unchanged') is not True
                        or report.get('protected_sha256')!=expected or report.get('model_calls')!=0
                        or report.get('native_qualification') is not False or report.get('green_approval') is not False
                        or report.get('delivery_approval') is not False):
                    raise ValueError('actual immutable Green handler proof missing')
            if phase=='review':
                report=json.loads(executed.stdout)
                if (report.get('operation')!='test_review_actual_registry_qualification_v2'
                        or report.get('snapshot_unchanged') is not True or report.get('readonly_mount') is not True
                        or report.get('direct_handler_denied') is not True or report.get('model_calls')!=0
                        or report.get('delivery_approval') is not False):
                    raise ValueError('real read-only registry proof missing')
            outcomes.append(dict(phase=phase,status='passed',container_retired=True))
            print(json.dumps(outcomes[-1]),flush=True)
        result=dict(operation='quality_author_filesystem_docker_qualification_v2',results=outcomes,
            phase='implementation_v2' if green else 'tests_only_v2',image=image_id,worker_image=worker['Id'] if worker else None,retained_volumes=volumes,archive=str(archive),native_qualification=False,model_calls=0,delivery_approval=False)
        save(archive/'result.json',result);return result
    finally:fixture.doCleanups()


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--namespace',required=True);p.add_argument('--image')
    p.add_argument('--worker-image')
    p.add_argument('--phase',choices=('tests_only_v2','implementation_v2'),default='tests_only_v2')
    p.add_argument('--observe-failure')
    a=p.parse_args()
    if a.observe_failure:result=observe_failure(a.namespace,a.observe_failure)
    elif a.image:result=qualify(a.namespace,a.image,a.worker_image,a.phase)
    else:p.error('--image or --observe-failure required')
    print(json.dumps(result,sort_keys=True))
