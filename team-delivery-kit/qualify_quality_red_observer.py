"""Zero-model Docker qualification on synthetic inputs baked into test images.

No native issue/enrollment, host mounts, Docker socket in jobs, credentials or
delivery approval. Stopped/unused resources are retired separately by the scoped
cleanup policy. A timeout must be inspected by the recorded name, never rerun.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import uuid

ROOT=Path(__file__).resolve().parent


def save(path,value):
    with os.fdopen(os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'w') as out:
        json.dump(value,out,sort_keys=True,indent=2);out.flush();os.fsync(out.fileno())


def command(args,**kwargs):
    return subprocess.run(args,text=True,capture_output=True,timeout=120,**kwargs)


def await_retirement(name):
    deadline=time.monotonic()+20
    while True:
        observed=subprocess.check_output(['docker','ps','-aq','--filter','name=^/'+name+'$'],text=True,timeout=10).strip()
        if not observed:return
        if time.monotonic()>=deadline:
            raise TimeoutError('probe retirement pending; observe exact name, never repeat execution')
        time.sleep(0.25)  # Read-only observation of the same removal acknowledgement.


def execution_args(namespace,name,image_id):
    from docker_grouping import args as group
    if not re.fullmatch(r'sha256:[a-f0-9]{64}',image_id):raise ValueError('exact local image ID required')
    if not re.fullmatch(re.escape(namespace)+r'-red-probe-[a-z0-9-]+',name):raise ValueError('exact grouped probe name required')
    return ['docker','run','--rm','--name',name,*group('quality-red-probe',namespace),
        '--label','delivery-kit.owner='+namespace+'-quality-red-probe',
        '--network','none','--read-only','--cap-drop','ALL',
        '--security-opt','no-new-privileges','--user','10000:10000',
        '--pids-limit','64','--memory','256m','--cpus','1',
        '--tmpfs','/tmp:rw,nosuid,nodev,size=32m,mode=1777',image_id]


def qualify(namespace,image):
    if not re.fullmatch(r'delivery-kit-[a-z0-9-]{1,48}',namespace):raise ValueError('exact delivery namespace required')
    if not re.fullmatch(r'delivery-kit-quality-red-observer:[A-Za-z0-9_.-]{1,64}',image):
        raise ValueError('locally built fixed observer image required')
    from controller_maintenance_cli import arguments
    maintenance=json.loads(subprocess.check_output(arguments(namespace,'status',''),text=True))
    if maintenance.get('stage')!='sealed' or maintenance.get('drained') is not True:
        raise ValueError('isolated qualification requires sealed drained controller')
    program=('import sys,json;sys.path.insert(0,"/");import broker as b,controller_maintenance as m;'
        'n=len(m.native_active(b));'
        'c=b.db();d=c.__enter__();'
        'l=d.execute("SELECT count(*) FROM leases WHERE status IN (?,?,?,?)",'
        '("creating","starting","running","closing")).fetchone()[0];'
        'c.__exit__(None,None,None);print(json.dumps(dict(native_active=n,active_leases=l)))')
    idle=json.loads(subprocess.check_output(['docker','exec',namespace+'-execution-broker-1',
        'python','-c',program],text=True,timeout=90))
    if idle!={'native_active':0,'active_leases':0}:raise ValueError('qualification must not compete with active work')
    unsettled=subprocess.check_output(['docker','ps','-aq','--filter',
        'label=delivery-kit.owner='+namespace+'-quality-red-probe'],text=True).strip()
    if unsettled:raise ValueError('existing probe handle must be observed before another qualification')
    info=json.loads(subprocess.check_output(['docker','image','inspect',image],text=True))[0]
    if (info.get('Config',{}).get('Labels',{}).get('delivery-kit.component')!='quality-red-observer'
            or info['Config'].get('Entrypoint')!=['python','/opt/quality/quality_red_observation.py']
            or info['Config'].get('User')!='10000:10000' or info['Config'].get('Volumes')):
        raise ValueError('fixed standalone observer image required')
    operation=str(uuid.uuid4())
    state=ROOT/('.local-'+namespace.removeprefix('delivery-kit-'))
    state.mkdir(mode=0o700,exist_ok=True)
    backups=state/'backups';backups.mkdir(mode=0o700,exist_ok=True)
    archive=backups/('quality-red-docker-'+operation)
    archive.mkdir(mode=0o700)
    save(archive/'operation.json',dict(operation=operation,namespace=namespace,observer_image_id=info['Id'],
        native_qualification=False,model_calls=0,delivery_approval=False,maintenance=maintenance,idle=idle))
    # Reuse the public synthetic unit fixture, never a product snapshot/session.
    sys.path.insert(0,str(ROOT/'tests'))
    from test_quality_red_observation import QualityRedObservationTests
    results=[]
    for case in ('valid_red','all_green','setup_assertion','snapshot_write'):
        fixture=QualityRedObservationTests();fixture.setUp()
        try:
            new=fixture.new
            if case=='all_green':new=new.replace(b'app.VALUE,1',b'app.VALUE,0')
            if case=='setup_assertion':new=new.replace(b' def test_new',b' def setUp(self):self.fail("setup")\n def test_new')
            if case=='snapshot_write':
                new=new.replace(b' def test_new(self):',
                    b' def test_new(self):\n  from pathlib import Path\n  Path(__file__).chmod(0o600)\n  Path(__file__).write_text("tampered")\n ')
            fixture.prepare(new=new)
            context=archive/case;context.mkdir(mode=0o700)
            for source in (fixture.base,fixture.snapshot):
                shutil.copytree(source,context/source.name)
            (context/'policy').mkdir()
            request=dict(plan=fixture.plan,task_id=fixture.task,
                base_manifest_sha256=fixture.prepared['base_manifest_sha256'],
                snapshot_manifest_sha256=fixture.prepared['manifest_sha256'])
            save(context/'policy/input.json',request)
            # Synthetic data only; the private parent stays 0700. Docker COPY
            # gives the unprivileged observer read access on its read-only root.
            os.chmod(context/'policy/input.json',0o644)
            (context/'Dockerfile').write_text('FROM '+image+'\nCOPY base /base\n'
                'COPY --chown=10000:10000 snapshot /snapshot\nCOPY policy /policy\n')
            tag='delivery-kit-quality-red-probe:'+operation[:8]+'-'+case
            name=namespace+'-red-probe-'+operation[:8]+'-'+case.replace('_','-')
            save(context/'intent.json',dict(image_tag=tag,container_name=name,case=case))
            built=command(['docker','build','--network=none','--pull=false','-t',tag,str(context)])
            save(context/'build.json',dict(exit_code=built.returncode,stdout=built.stdout,stderr=built.stderr))
            if built.returncode:raise RuntimeError('probe image build failed; inspect private receipt')
            built_info=json.loads(subprocess.check_output(['docker','image','inspect',tag],text=True))[0]
            image_id=built_info['Id']
            if built_info['Config'].get('Volumes'):raise ValueError('probe image inherited a volume')
            args=execution_args(namespace,name,image_id)
            observed=command(args)
            save(context/'execution.json',dict(argv=args,image_id=image_id,exit_code=observed.returncode,
                stdout=observed.stdout,stderr=observed.stderr))
            value=json.loads(observed.stdout)
            expected=0 if case=='valid_red' else 2
            if (observed.returncode!=expected or value.get('delivery_approval') is not False
                    or value.get('execution_authorized') is not False):
                raise ValueError('unexpected probe result; inspect preserved execution')
            if case=='valid_red':
                if value.get('operation')!='full_suite_red_observation_v2' or value['red']['tests_run']!=2:
                    raise ValueError('actual full suite Red required')
            elif value.get('operation')!='rejected_red_observation_v2':
                raise ValueError('negative must be refused')
            expected_category={'all_green':'suite_not_behavioral_red',
                'setup_assertion':'failure_outside_new_test_body',
                'snapshot_write':'suite_import_or_infrastructure_failure'}.get(case)
            if expected_category and value.get('category')!=expected_category:
                raise ValueError('negative failed for a different cause; not a qualified isolation proof')
            await_retirement(name)
            results.append(dict(case=case,image_id=image_id,image_tag=tag,container_retired=True,
                observed=value,exit_code=observed.returncode,host_mounts=False,network='none',root_readonly=True))
            print(json.dumps(dict(case=case,status='passed',delivery_approval=False)),flush=True)
        finally:fixture.tmp.cleanup()
    receipt=dict(operation='synthetic_docker_quality_red_qualification_v2',cases=results,
        observer_image_id=info['Id'],model_calls=0,native_qualification=False,delivery_approval=False,
        source_sha256=hashlib.sha256((ROOT/'quality_red_observation.py').read_bytes()).hexdigest(),archive=str(archive))
    save(archive/'result.json',receipt)
    return receipt


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--namespace',required=True);parser.add_argument('--image',required=True)
    options=parser.parse_args()
    print(json.dumps(qualify(options.namespace,options.image),sort_keys=True))
