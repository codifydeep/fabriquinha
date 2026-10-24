"""Fixed operator qualification of review pre-stop in a real isolated ACP worker.

No paid/model calls, native task, test approval or new Docker socket. A lost
reply preserves an unqualified operation; --observe never executes a new job.
"""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import uuid
from docker_grouping import args as grouping
from quality_git_candidate import require,Pending
from qualify_quality_red_observer import require_idle,save,await_retirement
from migrate_quality_candidate_pin import read
from install_quality_preview import save as save_state
from review_execution_evidence import validate as validate_execution_controls,validate_scale,scale_files

ROOT=Path(__file__).resolve().parent
GUARDS={'feedback':'quality_review_stop.py','phase':'quality_phase_tools.py',
    'verdict':'quality_review_verdict.py','installer':'install_quality_review_stop.py',
    'paging':'quality_review_paging.py','handler':'broker/review_tool_policy.py','budget':'quality_review_budget.py'}


def sha(raw):return hashlib.sha256(raw).hexdigest()


def validate_report(report,guards):
    require(isinstance(report,dict) and report.get('operation')=='real_hermes_review_stop_loop_canary_v1'
        and report.get('status')=='passed' and report.get('provider')=='fixed_loopback_not_model'
        and report.get('model_calls')==0 and type(report.get('model_calls')) is int
        and report.get('fixed_provider_calls')==4 and report.get('feedback_rounds')==1
        and report.get('premature_after_tests_forced_read') is True
        and report.get('same_agent') is True and report.get('max_iterations')==40
        and report.get('acp') is True and report.get('protected_files_unchanged') is True
        and report.get('tests_approved') is False and report.get('delivery_approval') is False
        and isinstance(report.get('guard_sources'),dict)
        and all(report['guard_sources'].get(key)==value for key,value in guards.items()))
    validate_execution_controls(report.get('execution_controls'))
    validate_scale(report.get('scale_controls'))
    require(type(report.get('total_fixed_provider_calls')) is int
        and report['total_fixed_provider_calls']==15+report['scale_controls']['summary_provider_calls']
        and report.get('fixture_source_sha256')==sha((ROOT/'review_execution_evidence.py').read_bytes()))
    return report


def observe(archive,identity):
    state=json.loads(read(archive/'state.json'));require(state['identity']==identity)
    if state['stage']=='qualified':
        receipt=state['receipt']
        require(receipt['operation']=='qualified_review_stop_worker_v1' and receipt['namespace']==identity['namespace']
            and receipt['qualification_id']==identity['operation'] and receipt['worker_image']==identity['image']
            and receipt['guards']==identity['guards'] and receipt['script_sha256']==identity['script_sha256']
            and receipt['fixture_sha256']==identity['fixture_sha256']
            and receipt['container_retired'] is True and receipt['tests_approved'] is False
            and receipt['delivery_approval'] is False and receipt['model_calls']==0)
        validate_report(receipt['report'],identity['guards']);return receipt
    if state['stage']=='execution_intent' and (archive/'output.json').exists():
        return finish(archive,state)
    return dict(stage=state['stage'],operation=identity['operation'],qualified=False,model_calls=0,
        next_action='observe the same owned container/operation; never replay create/start',delivery_approval=False)


def finish(archive,state):
    """Resume only the receipt after successful output; never rerun Docker."""
    identity=state['identity'];namespace=identity['namespace']
    saved=json.loads(read(archive/'output.json'))
    try:
        require(saved['returncode']==0 and require_idle(namespace)[0]==state['maintenance']
            and sha((ROOT/'tests/quality_review_stop_canary.py').read_bytes())==identity['script_sha256']
            and sha((ROOT/'review_execution_evidence.py').read_bytes())==identity['fixture_sha256']
            and all(sha((ROOT/path).read_bytes())==identity['guards'][key] for key,path in GUARDS.items()))
        await_retirement(state['container_name'])
        reports=[]
        for line in saved['stdout'].splitlines():
            try:value=json.loads(line)
            except ValueError:continue
            if isinstance(value,dict) and value.get('operation')=='real_hermes_review_stop_loop_canary_v1':reports.append(value)
        require(len(reports)==1);report=validate_report(reports[0],identity['guards'])
    except Exception:
        state.update(stage='technical_blocked');save_state(archive/'state.json',state);raise
    receipt=dict(operation='qualified_review_stop_worker_v1',namespace=namespace,qualification_id=identity['operation'],
        worker_image=identity['image'],guards=identity['guards'],script_sha256=identity['script_sha256'],report=report,
        fixture_sha256=identity['fixture_sha256'],
        output_sha256=sha(saved['stdout'].encode()),command_sha256=state['command_sha256'],
        maintenance_operation=state['maintenance']['operation_id'],container_retired=True,
        model_calls=0,tests_approved=False,delivery_approval=False)
    state.update(stage='qualified',receipt=receipt);save_state(archive/'state.json',state)
    return receipt


def qualify(namespace,image,operation,*,observe_only=False):
    require(re.fullmatch(r'delivery-kit-[a-z0-9-]{1,48}',namespace)
        and re.fullmatch(r'sha256:[a-f0-9]{64}',image) and str(uuid.UUID(operation))==operation)
    script=ROOT/'tests/quality_review_stop_canary.py';raw=script.read_bytes()
    guards={key:sha((ROOT/path).read_bytes()) for key,path in GUARDS.items()}
    identity=dict(namespace=namespace,image=image,operation=operation,script_sha256=sha(raw),guards=guards,
        fixture_sha256=sha((ROOT/'review_execution_evidence.py').read_bytes()))
    private=ROOT/('.local-'+namespace.removeprefix('delivery-kit-'))/'backups'
    archive=private/('quality-review-stop-'+operation)
    if archive.exists():return observe(archive,identity)
    require(not observe_only)
    maintenance,_=require_idle(namespace)
    proxy=subprocess.run(['docker','inspect',namespace+'-model-proxy-1','--format','{{.State.Running}}'],
        capture_output=True,text=True,timeout=15)
    require(proxy.returncode==0 and proxy.stdout.strip()=='false')
    metadata=json.loads(subprocess.check_output(['docker','image','inspect',image],text=True,timeout=15))[0]
    require(metadata['Id']==image and metadata['Config'].get('User')=='10000:10000'
        and not metadata['Config'].get('Volumes')
        and metadata['Config'].get('Labels',{}).get('delivery-kit.component')=='quality-author-worker')
    unsettled=subprocess.check_output(['docker','ps','-aq','--filter',
        'label=delivery-kit.owner='+namespace+'-quality-review-stop'],text=True,timeout=15).strip()
    require(not unsettled)
    for previous in private.glob('quality-review-stop-*'):
        prior=json.loads(read(previous/'state.json'))
        require(prior['stage'] in ('qualified','technical_blocked'))
    # Literal fixture data only. Never import/execute a canary to discover inputs.
    assignments=[node for node in ast.parse(raw).body if isinstance(node,ast.Assign)
        and len(node.targets)==1 and isinstance(node.targets[0],ast.Name) and node.targets[0].id=='FILES']
    require(len(assignments)==1);files=ast.literal_eval(assignments[0].value)
    require(set(files)=={'app.py','tests/test_new.py'} and all(isinstance(v,bytes) and len(v)<=1024 for v in files.values()))
    files={**files,**scale_files()}
    archive.mkdir(mode=0o700);delivery=archive/'delivery';delivery.mkdir(mode=0o755);os.chmod(delivery,0o755)
    for name,data in files.items():
        path=delivery/name;path.parent.mkdir(mode=0o755,exist_ok=True)
        os.chmod(path.parent,0o755)
        with os.fdopen(os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o444),'wb') as output:output.write(data)
        os.chmod(path,0o444)
    name=namespace+'-review-stop-'+operation
    existing=subprocess.check_output(['docker','ps','-aq','--filter','name=^/'+name+'$'],text=True,timeout=15).strip()
    require(not existing)
    command=['docker','run','--rm','--name',name,*grouping('review-stop-canary',namespace=namespace),
        '--label','delivery-kit.owner='+namespace+'-quality-review-stop','--label','delivery-kit.operation='+operation,
        '--network','none','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges',
        '--memory','256m','--pids-limit','64','--cpus','1',
        '--tmpfs','/tmp:rw,nosuid,nodev,size=32m,mode=1777',
        '--mount','type=bind,source='+str(delivery)+',target=/delivery,readonly',
        '--mount','type=bind,source='+str(script)+',target=/probe.py,readonly',
        '--mount','type=bind,source='+str(ROOT/'review_execution_evidence.py')+',target=/review_execution_evidence.py,readonly',
        '--env','REVIEW_STOP_CANARY_ACP=1','--entrypoint','python',image,'/probe.py']
    state=dict(identity=identity,stage='execution_intent',maintenance=maintenance,command_sha256=sha(json.dumps(command).encode()),
        container_name=name,model_calls=0,delivery_approval=False)
    save(archive/'state.json',state)
    try:result=subprocess.run(command,capture_output=True,text=True,timeout=150)
    except subprocess.TimeoutExpired:
        state.update(stage='outcome_unknown');save_state(archive/'state.json',state)
        raise Pending('observe same fixed canary; never create a replacement') from None
    save(archive/'output.json',dict(returncode=result.returncode,stdout=result.stdout,stderr=result.stderr))
    return finish(archive,state)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('namespace','worker-image','operation'):parser.add_argument('--'+key,required=True)
    parser.add_argument('--observe',action='store_true');args=parser.parse_args()
    print(json.dumps(qualify(args.namespace,args.worker_image,args.operation,observe_only=args.observe),sort_keys=True))
