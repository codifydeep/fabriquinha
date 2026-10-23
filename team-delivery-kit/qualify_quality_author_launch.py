"""Docker/ACP qualification in the existing controller, isolated synthetic DB.

No new Docker-socket mount, production DB mutation, native issue or model prompt.
An incomplete operation fences another run. Preserve intents, copied source,
state and logs; retire only its exact settled containers, never any volume.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import uuid
from docker_grouping import args as grouped
from qualify_quality_red_observer import require_idle,save,command,await_retirement

ROOT=Path(__file__).resolve().parent
SOURCES={
    'broker/server.py':'candidate_broker.py','broker/native.py':'native.py',
    'broker/controller_maintenance.py':'controller_maintenance.py','broker/maintenance_job_clock.py':'maintenance_job_clock.py',
    'broker/quality_lifecycle_v2.py':'quality_lifecycle_v2.py','broker/quality_lifecycle_enrollment.py':'quality_lifecycle_enrollment.py',
    'broker/quality_author_admission.py':'quality_author_admission.py','broker/quality_author_worker.py':'quality_author_worker.py',
    'broker/quality_author_launch.py':'quality_author_launch.py','broker/quality_red_capture.py':'quality_red_capture.py',
    'broker/quality_red_snapshot.py':'quality_red_snapshot.py','broker/quality_progress.py':'quality_progress.py',
    'broker/quality_test_review.py':'quality_test_review.py',
    'broker/quality_worker_runtime.py':'quality_worker_runtime.py',
    'broker/quality_review_launch.py':'quality_review_launch.py','broker/quality_launch_router.py':'quality_launch_router.py',
    'broker/quality_review_reads.py':'quality_review_reads.py','broker/quality_review_attestation.py':'quality_review_attestation.py',
    'broker/quality_implementation_admission.py':'quality_implementation_admission.py',
    'broker/quality_implementation_launch.py':'quality_implementation_launch.py',
    'broker/quality_delivery_capture.py':'quality_delivery_capture.py',
    'broker/quality_candidate_binding.py':'quality_candidate_binding.py',
    'broker/quality_candidate_rpc.py':'quality_candidate_rpc.py',
    'broker/quality_green_capture.py':'quality_green_capture.py',
    'broker/quality_sensitivity_capture.py':'quality_sensitivity_capture.py',
    'broker/quality_team_progress.py':'quality_team_progress.py',
    'broker/read_stream_receipts.py':'read_stream_receipts.py','artifact_read_evidence.py':'artifact_read_evidence.py',
    'broker/validation_job.py':'validation_job.py',
    'broker/test_first_job.py':'test_first_job.py','broker/worker_creation_intent.py':'worker_creation_intent.py',
    'broker/acp_startup.py':'acp_startup.py','broker/acp_transport.py':'acp_transport.py',
    'broker/helper_cleanup.py':'helper_cleanup.py','portable_contract.py':'portable_contract.py',
    'test_runner_policy.py':'test_runner_policy.py','docker_grouping.py':'docker_grouping.py',
    'model_policy.py':'model_policy.py','quality_phase_tools.py':'quality_phase_tools.py','execution_context.py':'execution_context.py',
    'tests/quality_launch_docker_probe.py':'quality_launch_docker_probe.py'}


def validate_report(report):
    if (report.get('status')!='passed' or report.get('docker')!='real' or report.get('acp')!='real'
            or report.get('native_api')!='synthetic_fixture' or report.get('delivery_approval') is not False
            or any(type(report.get(k)) is not int or report[k]!=0 for k in ('model_calls','prompts_sent'))):
        raise ValueError('actual zero-model fixture observations required, never delivery approval')
    frames=report.get('frames')
    if (not isinstance(frames,list) or [f.get('method') for f in frames]!=['initialize','session/new']
            or any(f.get('status')!='passed' or not re.fullmatch('[a-f0-9]{64}',str(f.get('response_sha256'))) for f in frames)):
        raise ValueError('complete actual initialize/session-new receipts required')
    if 'review_launch' in report:
        review=report['review_launch']
        if (not isinstance(review,dict) or review.get('status')!='passed'
                or review.get('tests_approved') is not False or review.get('delivery_approval') is not False
                or review.get('snapshot_mount')!='readonly' or review.get('source_task')!=report.get('task_id')
                or review.get('task_id')==report.get('task_id') or review.get('request_id')==report.get('request_id')
                or not re.fullmatch('[a-f0-9]{64}',str(review.get('manifest_sha256')))
                or [f.get('method') for f in review.get('frames',[])]!=['initialize','session/new']
                or any(f.get('status')!='passed' or not re.fullmatch('[a-f0-9]{64}',str(f.get('response_sha256')))
                    for f in review.get('frames',[]))):
            raise ValueError('actual readonly review launch required, never test approval')
        for key in ('task_id','request_id'):
            if str(uuid.UUID(review[key]))!=review[key]:raise ValueError('exact review execution identity required')
        if 'handler_byte_binding' in review and review['handler_byte_binding'] is not True:
            raise ValueError('actual handler byte binding required when claimed')


def input_config(archive,metadata):
    from broker.quality_lifecycle_v2 import POLICY,digest
    operation=metadata['operation'];namespace=metadata['namespace']
    ids={key:str(uuid.uuid5(uuid.UUID(operation),key)) for key in ('issue','run','task','author','reviewer','workspace','runtime')}
    spec=json.loads((archive/'base/contract.json').read_text())
    manifest=(archive/'base/manifest.json').read_bytes();base=json.loads(manifest)
    plan=dict(version=2,policy=POLICY,run_id=ids['run'],issue_id=ids['issue'],author=ids['author'],reviewer=ids['reviewer'],
        contract_sha256=digest(spec),base_sha=base['base_sha'],criteria=['A01'],
        baseline_tests={'tests/test_old.py':base['files']['tests/test_old.py']},new_tests=['tests/test_new.py'],
        product_files=['app.py'],protected_files=['AGENTS.md','tests/test_old.py','tests/test_new.py'],
        criterion_tests={'A01':[dict(path='tests/test_new.py',method='test_new')]})
    result=dict(namespace=namespace,owner=metadata['owner'],operation=operation,task_id=ids['task'],plan=plan,contract=spec,
        settings=dict(workspace_id=ids['workspace'],runtime_id=ids['runtime'],agents={ids['author']:'implementation',ids['reviewer']:'review'}),
        base=dict(issue_id=ids['issue'],base_sha=base['base_sha'],volume=metadata['base_volume'],manifest_sha256=hashlib.sha256(manifest).hexdigest()),
        **metadata['images'])
    if metadata.get('review_chain'):
        actors={key:str(uuid.uuid5(uuid.UUID(operation),key)) for key in ('techlead','cto','review_task','review_wakeup')}
        result.update(review_chain=True,review_task=actors['review_task'],review_wakeup=actors['review_wakeup'],
            QUALITY_REVIEW_WORKER_IMAGE=metadata['images']['QUALITY_WORKER_IMAGE'],
            QUALITY_TECHLEAD=actors['techlead'],QUALITY_CTO=actors['cto'])
        result['settings']['agents'].update({actors['techlead']:'planning',actors['cto']:'planning'})
    return result


def execute_probe(archive,controller,remote,config,maintenance):
    support=archive/'source';support.mkdir(mode=0o700,exist_ok=True)
    hashes={}
    for original,target in SOURCES.items():
        source=ROOT/original;destination=support/target
        if source.is_symlink():raise ValueError('regular public source required')
        if destination.exists() and destination.read_bytes()!=source.read_bytes():raise ValueError('original transferred source changed; explicit new qualification required')
        if not destination.exists():shutil.copyfile(source,destination)
        hashes[target]=hashlib.sha256(source.read_bytes()).hexdigest()
    config=dict(config,source_sha256=hashes)
    for path in (archive/'input.json',support/'input.json'):
        if path.exists():
            if json.loads(path.read_text())!=config:raise ValueError('immutable qualification input drift')
        else:save(path,config)
    tarpath=archive/'source-transfer-v2.tar'
    if tarpath.exists():raise ValueError('transfer already attempted; inspect its exact outcome before continuation')
    packaged=command(['tar','-cf',str(tarpath),'-C',str(support),*SOURCES.values(),'input.json'])
    if packaged.returncode:raise ValueError('source packaging failed')
    os.chmod(tarpath,0o600)
    args=['docker','exec','-i',controller,'tar','-xf','-','--no-same-owner','-C',remote]
    save(archive/'source-transfer-v2-intent.json',dict(argv=args,tar_sha256=hashlib.sha256(tarpath.read_bytes()).hexdigest()))
    transferred=subprocess.run(args,input=tarpath.read_bytes(),capture_output=True,timeout=120)
    save(archive/'source-transfer-v2-result.json',dict(exit_code=transferred.returncode,
        stdout=transferred.stdout.decode(errors='replace'),stderr=transferred.stderr.decode(errors='replace')))
    if transferred.returncode:raise ValueError('observe original source transfer; no new operation')
    args=['docker','exec',controller,'python',remote+'/quality_launch_docker_probe.py']
    save(archive/'process-intent.json',dict(argv=args))
    executed=command(args)
    save(archive/'process-result.json',dict(exit_code=executed.returncode,stdout=executed.stdout,stderr=executed.stderr))
    exported=subprocess.run(['docker','exec',controller,'tar','-cf','-','-C',remote,'state'],capture_output=True,timeout=120)
    save(archive/'state-export-result.json',dict(exit_code=exported.returncode,stderr=exported.stderr.decode(errors='replace')))
    if exported.returncode:raise ValueError('state archive failed; do not retire or repeat')
    state_tar=archive/'state.tar'
    with os.fdopen(os.open(state_tar,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'wb') as out:out.write(exported.stdout)
    with tarfile.open(state_tar) as bundled:
        for member in bundled.getmembers():
            path=Path(member.name)
            if path.is_absolute() or '..' in path.parts or not (member.isfile() or member.isdir()) or path.parts[0]!='state':
                raise ValueError('unsafe state archive; preserve original without extraction')
    extracted=command(['tar','-xf',str(state_tar),'-C',str(archive)])
    if extracted.returncode:raise ValueError('state extraction failed; no retirement')
    for folder,dirs,files in os.walk(archive/'state'):
        os.chmod(folder,0o700)
        for file in files:os.chmod(Path(folder)/file,0o600)
    report=json.loads((archive/'state/run-result.json').read_text())
    validate_report(report)
    if executed.returncode or report['status']!='passed':raise ValueError('real launch qualification failed; inspect preserved process/state, no replay')
    return finish_retirement(config['namespace'],config['operation'])


def resume_before_execution(namespace,operation):
    if str(uuid.UUID(operation))!=operation:raise ValueError('exact operation identity required')
    maintenance,idle=require_idle(namespace)
    archive=ROOT/('.local-'+namespace.removeprefix('delivery-kit-'))/'backups'/('quality-launch-docker-'+operation)
    metadata=json.loads((archive/'operation.json').read_text())
    if metadata['operation']!=operation or metadata['maintenance']!=maintenance:raise ValueError('original maintenance/operation drift')
    if (archive/'process-intent.json').exists() or (archive/'source-transfer-v2-intent.json').exists():
        raise ValueError('execution/transfer already attempted; observe original process, never restart')
    remote=json.loads((archive/'remote-allocation-result.json').read_text())['path']
    if not re.fullmatch('/tmp/dk-quality-launch-[A-Za-z0-9]{6}',remote):raise ValueError('exact private allocation required')
    controller=metadata['controller']
    absent=command(['docker','exec',controller,'test','!','-e',remote+'/state'])
    if absent.returncode:raise ValueError('candidate state already exists; continuation forbidden')
    metadata=dict(metadata,namespace=namespace)
    save(archive/'source-transfer-continuation.json',dict(condition='docker_cp_cannot_access_tmpfs',candidate_not_started=True,original_base_preserved=True))
    return execute_probe(archive,controller,remote,input_config(archive,metadata),maintenance)


def image(tag,component):
    if not re.fullmatch('delivery-kit-quality-'+component+r':[A-Za-z0-9_.-]{1,64}',tag):raise ValueError('fixed local image required')
    info=json.loads(subprocess.check_output(['docker','image','inspect',tag],text=True))[0]
    if (info['Config'].get('Volumes') or info['Config'].get('Labels',{}).get('delivery-kit.component')!='quality-'+component):
        raise ValueError('dedicated qualified image with no inherited volumes required')
    return info


def observe_retirement(archive,owner,namespace):
    """Only after the isolated process and all actual jobs have settled."""
    ids=subprocess.check_output(['docker','ps','-aq','--no-trunc','--filter','label=delivery-kit.owner='+owner],text=True).split()
    for ident in ids:
        info=json.loads(subprocess.check_output(['docker','inspect',ident],text=True))[0]
        labels=info['Config'].get('Labels',{})
        if (info['Id']!=ident or labels.get('delivery-kit.owner')!=owner
                or labels.get('com.docker.compose.project')!=namespace+'-tests'):
            raise ValueError('retirement ownership drift')
        if info['State']['Status'] not in ('created','running','exited'):raise ValueError('Docker effects unsettled; observe only')
        metadata=archive/(ident+'-metadata.json')
        if metadata.exists():
            old=json.loads(metadata.read_text())
            if old['Id']!=info['Id'] or old['Image']!=info['Image']:raise ValueError('archived identity changed')
        else:save(metadata,{k:info[k] for k in ('Id','Name','Image','State','Mounts')})
        if not (archive/(ident+'-logs.json')).exists():
            logs=command(['docker','logs','--timestamps',ident])
            save(archive/(ident+'-logs.json'),dict(stdout=logs.stdout,stderr=logs.stderr))
        current=json.loads(subprocess.check_output(['docker','inspect',ident],text=True))[0]
        if (current['Id']!=ident or current['Image']!=info['Image']
                or current['Config'].get('Labels',{}).get('delivery-kit.owner')!=owner):raise ValueError('retirement identity changed')
        if current['State']['Running']:
            if (archive/(ident+'-stop-intent.json')).exists():raise ValueError('observe previous stop; never repeat it')
            save(archive/(ident+'-stop-intent.json'),dict(container_id=ident))
            stopped=command(['docker','stop','--time','10',ident])
            save(archive/(ident+'-stop-result.json'),dict(exit_code=stopped.returncode,stdout=stopped.stdout,stderr=stopped.stderr))
            if stopped.returncode:raise ValueError('stop outcome requires observation, not repeated stop/delete')
        current=json.loads(subprocess.check_output(['docker','inspect',ident],text=True))[0]
        if current['State']['Running'] or current['Config'].get('Labels',{}).get('delivery-kit.owner')!=owner:
            raise ValueError('container still active or changed; not removed')
        if (archive/(ident+'-remove-intent.json')).exists():raise ValueError('observe previous removal; never repeat it')
        save(archive/(ident+'-remove-intent.json'),dict(container_id=ident,force=False,volumes_deleted=0))
        removed=command(['docker','rm',ident])
        save(archive/(ident+'-remove-result.json'),dict(exit_code=removed.returncode,stdout=removed.stdout,stderr=removed.stderr))
        if removed.returncode:raise ValueError('removal outcome requires observation, never replay')
        await_retirement(info['Name'].lstrip('/'))
    return len(ids)


def finish_retirement(namespace,operation):
    """Continue after a confirmed terminal process; no candidate rerun or grant."""
    if str(uuid.UUID(operation))!=operation:raise ValueError('exact qualification identity required')
    maintenance,idle=require_idle(namespace)
    archive=ROOT/('.local-'+namespace.removeprefix('delivery-kit-'))/'backups'/('quality-launch-docker-'+operation)
    if (archive/'result.json').exists():return json.loads((archive/'result.json').read_text())
    metadata=json.loads((archive/'operation.json').read_text())
    process=json.loads((archive/'process-result.json').read_text())
    report=json.loads((archive/'state/run-result.json').read_text())
    validate_report(report)
    if (metadata['operation']!=operation or metadata['maintenance']!=maintenance
            or metadata['owner']!=namespace+'-quality-launch-'+operation[:8]
            or process['exit_code']!=0 or report['status']!='passed' or report['model_calls']!=0
            or report['prompts_sent']!=0 or report['native_api']!='synthetic_fixture'):
        raise ValueError('proved terminal zero-model qualification required; never infer completion')
    with sqlite3.connect('file:'+str(archive/'state/leases.sqlite')+'?mode=ro',uri=True) as con:
        if con.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise ValueError('private state archive corrupt')
        events=con.execute('SELECT method,success FROM acp_events ORDER BY rowid').fetchall()
        expected=[('initialize',1),('session/new',1)]*(2 if 'review_launch' in report else 1)
        if events!=expected:raise ValueError('actual ACP events missing or a prompt was sent')
        bindings=con.execute('SELECT request_id,task_id FROM quality_author_admissions').fetchall()
        if bindings!=[(report['request_id'],report['task_id'])]:raise ValueError('admission report identity drift')
        if 'review_launch' in report:
            reviewed=report['review_launch']
            rows=con.execute('SELECT request_id,task_id FROM quality_review_admissions').fetchall()
            if rows!=[(reviewed['request_id'],reviewed['task_id'])]:raise ValueError('review admission identity drift')
            state=json.loads(con.execute('SELECT state FROM quality_test_reviews WHERE source_task=?',(report['task_id'],)).fetchone()[0])
            if state['stage']!='admitted' or state['tests_approved'] is not False:raise ValueError('review launch must not approve tests')
            for row in con.execute('SELECT state FROM test_first_jobs'):
                if json.loads(row[0])['stage']!='complete':raise ValueError('fixed copy job unsettled')
        if any(json.loads(row[0])['stage']!='complete' for row in con.execute('SELECT state FROM validation_jobs')):
            raise ValueError('fixed jobs unsettled; observe original execution')
        if any(json.loads(row[0])['stage'] not in ('start_acknowledged','start_running_observed')
                for row in con.execute('SELECT state FROM worker_creation_intents')):
            raise ValueError('worker creation/start unsettled; no cleanup or replay')
    observe_retirement(archive,metadata['owner'],namespace)
    remaining=subprocess.check_output(['docker','ps','-aq','--no-trunc','--filter','label=delivery-kit.owner='+metadata['owner']],text=True).strip()
    if remaining:raise ValueError('retirement pending; observe original identities')
    after,_=require_idle(namespace)
    if after!=maintenance:raise ValueError('installed maintenance changed during qualification')
    result=dict(report,containers_retired=len(list(archive.glob('*-metadata.json'))),volumes_deleted=0,
        archive=str(archive),installed_controller_unchanged=True)
    save(archive/'result.json',result);return result


def qualify(namespace,prep_tag,worker_tag,copy_tag,observer_tag,*,review_chain=False):
    maintenance,idle=require_idle(namespace)
    controller=namespace+'-execution-broker-1'
    proxy=subprocess.run(['docker','inspect',namespace+'-model-proxy-1','--format','{{.State.Running}}'],capture_output=True,text=True)
    if proxy.returncode or proxy.stdout.strip()!='false':raise ValueError('model proxy must already be stopped for zero-model qualification')
    images={key:image(tag,component) for key,tag,component in (
        ('QUALITY_PREP_IMAGE',prep_tag,'author-prep'),('QUALITY_WORKER_IMAGE',worker_tag,'author-worker'),
        ('QUALITY_COPY_IMAGE',copy_tag,'red-copy'),('QUALITY_RED_IMAGE',observer_tag,'red-observer'))}
    backups=ROOT/('.local-'+namespace.removeprefix('delivery-kit-'))/'backups'
    for previous in backups.glob('quality-launch-docker-*'):
        if (previous/'operation.json').exists() and not (previous/'result.json').exists():
            raise ValueError('unfinished launch qualification; inspect original process/intent, never repeat')
    operation=str(uuid.uuid4());archive=backups/('quality-launch-docker-'+operation);archive.mkdir(mode=0o700)
    owner=namespace+'-quality-launch-'+operation[:8]
    ids={key:str(uuid.uuid5(uuid.UUID(operation),key)) for key in ('issue','run','task','author','reviewer','workspace','runtime')}
    base_volume=namespace+'-base-'+ids['issue']
    save(archive/'operation.json',dict(operation=operation,owner=owner,namespace=namespace,controller=controller,
        maintenance=maintenance,idle=idle,base_volume=base_volume,images={k:v['Id'] for k,v in images.items()},
        native_api='synthetic_fixture',review_chain=review_chain,model_calls=0,prompts_sent=0,delivery_approval=False))
    sys.path.insert(0,str(ROOT/'tests'))
    from test_quality_red_observation import QualityRedObservationTests
    fixture=QualityRedObservationTests();fixture.setUp()
    try:
        fixture.spec['test_image']=observer_tag.split(':')[0]+'@'+images['QUALITY_RED_IMAGE']['Id']
        fixture.prepare();shutil.copytree(fixture.base,archive/'base')
        labels={'delivery-kit.owner':owner,'delivery-kit.issue-id':ids['issue'],'delivery-kit.base-sha':'b'*40,
            'delivery-kit.qualification':operation,'delivery-kit.lifecycle':'qualification-proof',
            'com.docker.compose.project':namespace+'-tests'}
        args=['docker','volume','create','--driver','local']
        for key,value in labels.items():args+=['--label',key+'='+value]
        args+=[base_volume];save(archive/'base-volume-intent.json',dict(argv=args))
        created=command(args);save(archive/'base-volume-result.json',dict(exit_code=created.returncode,stdout=created.stdout,stderr=created.stderr))
        if created.returncode:raise ValueError('observe original volume create outcome')
        actual=json.loads(subprocess.check_output(['docker','volume','inspect',base_volume],text=True))[0]
        if actual.get('Labels')!=labels or actual.get('Name')!=base_volume:raise ValueError('base ownership drift')
        (archive/'Dockerfile').write_text('FROM '+prep_tag+'\nCOPY base /base\n')
        tag='delivery-kit-quality-launch-fixture:'+operation[:8]
        save(archive/'build-intent.json',dict(tag=tag))
        built=command(['docker','build','--network=none','--pull=false','-t',tag,str(archive)])
        save(archive/'build-result.json',dict(exit_code=built.returncode,stdout=built.stdout,stderr=built.stderr))
        if built.returncode:raise ValueError('qualification build failed; inspect original operation')
        name=namespace+'-launch-base-'+operation[:8]
        manifest=hashlib.sha256((fixture.base/'manifest.json').read_bytes()).hexdigest()
        initialize=['docker','run','--rm','--name',name,*grouped('quality-launch-base',namespace),
            '--label','delivery-kit.owner='+owner,'--network','none','--read-only','--cap-drop','ALL',
            '--security-opt','no-new-privileges','--user','10000:10000','--pids-limit','16','--memory','128m',
            '--mount','type=volume,src='+base_volume+',dst=/base,readonly','--entrypoint','python',tag,'-c',
            'import hashlib;from pathlib import Path;print(hashlib.sha256(Path("/base/manifest.json").read_bytes()).hexdigest())']
        save(archive/'base-init-intent.json',dict(argv=initialize))
        initialized=command(initialize);save(archive/'base-init-result.json',dict(exit_code=initialized.returncode,stdout=initialized.stdout,stderr=initialized.stderr))
        if initialized.returncode or initialized.stdout.strip()!=manifest:raise ValueError('actual base manifest mismatch')
        await_retirement(name)
        save(archive/'remote-allocation-intent.json',dict(controller=controller))
        allocated=command(['docker','exec',controller,'mktemp','-d','/tmp/dk-quality-launch-XXXXXX'])
        remote=allocated.stdout.strip()
        save(archive/'remote-allocation-result.json',dict(exit_code=allocated.returncode,path=remote))
        if allocated.returncode or not re.fullmatch('/tmp/dk-quality-launch-[A-Za-z0-9]{6}',remote):raise ValueError('remote allocation unknown; never repeat')
        metadata=json.loads((archive/'operation.json').read_text())
        return execute_probe(archive,controller,remote,input_config(archive,metadata),maintenance)
    finally:fixture.doCleanups()


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--namespace',required=True)
    for key in ('prep','worker','copy','observer'):p.add_argument('--'+key+'-image')
    p.add_argument('--resume-before-execution')
    p.add_argument('--finish-retirement')
    p.add_argument('--review-chain',action='store_true',help='Synthetic author/Red/review launch, no model or test approval')
    a=p.parse_args()
    if a.finish_retirement:result=finish_retirement(a.namespace,a.finish_retirement)
    elif a.resume_before_execution:result=resume_before_execution(a.namespace,a.resume_before_execution)
    elif all((a.prep_image,a.worker_image,a.copy_image,a.observer_image)):
        result=qualify(a.namespace,a.prep_image,a.worker_image,a.copy_image,a.observer_image,review_chain=a.review_chain)
    else:p.error('four fixed images or --resume-before-execution required')
    print(json.dumps(result,sort_keys=True))
