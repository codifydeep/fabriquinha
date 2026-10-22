"""Persistent full-suite Green from a trusted local Git binding and fixed job.

Never accepts model reports or a worker-selected SHA/command/test subset.
Green observation is evidence, not sensitivity, delivery review or homologation.
"""
import hashlib
import json
import re
import time
from docker_grouping import grouped_create
try:
    from . import quality_candidate_binding as binding,quality_delivery_capture as delivery
    from . import controller_maintenance as maintenance,maintenance_job_clock as clock,validation_job
    from .test_first_job import digest
except ImportError:
    import quality_candidate_binding as binding,quality_delivery_capture as delivery
    import controller_maintenance as maintenance,maintenance_job_clock as clock,validation_job
    from test_first_job import digest

quality=delivery.quality
require=delivery.require


def initialize(con):
    con.execute('CREATE TABLE IF NOT EXISTS quality_green_captures('
        'request_id TEXT PRIMARY KEY,context TEXT,state TEXT,context_sha256 TEXT,state_sha256 TEXT)')


def load(b,request):
    with b.db() as con:
        initialize(con)
        row=con.execute('SELECT context,state,context_sha256,state_sha256 FROM quality_green_captures '
            'WHERE request_id=?',(request,)).fetchone()
    if not row:return None
    context,state=json.loads(row[0]),json.loads(row[1])
    require(quality.digest(context)==row[2] and quality.digest(state)==row[3]
        and context['namespace']==b.PREFIX and context['request_id']==request
        and state['stage'] in ('awaiting_green','awaiting_sensitivity','technical_blocked')
        and all(state.get(k) is False for k in ('execution_authorized','green_approved','delivery_approval')))
    if state['stage']=='awaiting_sensitivity':
        evidence=state['observation']['green']
        quality.green(context['plan'],context['freeze']['red'],context['freeze']['test_review'],evidence)
        require(evidence['commit_sha']==context['commit_sha'] and evidence['manifest_sha256']==context['manifest_sha256']
            and evidence['task_id']==context['task_id'])
    return context,state


def save(b,request,context,before,after):
    with b.LOCK,b.db() as con:
        maintenance.transaction(con)
        if maintenance.current(con):raise validation_job.Pending('maintenance preserves original Green job')
        changed=con.execute('UPDATE quality_green_captures SET state=?,state_sha256=? '
            'WHERE request_id=? AND context_sha256=? AND state_sha256=?',
            (json.dumps(after,sort_keys=True),quality.digest(after),request,quality.digest(context),quality.digest(before)))
        require(changed.rowcount==1)
    return after


def provenance(b,request):
    recorded=binding.load(b,request);require(recorded is not None)
    identity,receipt=recorded;packet=identity['packet'];d=packet['descriptor']
    context,state=delivery.load(b,request)
    require(quality.digest(context)==d['capture_context_sha256'] and quality.digest(state)==d['capture_state_sha256']
        and state['stage']=='awaiting_git_binding' and context['freeze']['plan']==packet['plan']
        and context['freeze']['frozen_tests']==packet['frozen_tests']
        and delivery.admission.snapshot.volume_identity(b.docker('GET','/volumes/'+context['name']),
            dict(name=context['name'],labels=context['labels']))==state['volume_identity'])
    return dict(namespace=b.PREFIX,request_id=request,task_id=d['task_id'],binding_sha256=quality.digest(receipt),
        descriptor_sha256=quality.digest(d),plan=packet['plan'],freeze=context['freeze'],base=context['base'],
        volume=context['name'],volume_identity=state['volume_identity'],labels=context['labels'],
        manifest_sha256=d['manifest_sha256'],commit_sha=receipt['commit_sha'],owner=context['techlead'],cto=context['cto'])


def payload(b,context):
    request=dict(operation='observe_green_v2',plan=context['plan'],task_id=context['task_id'],
        base_manifest_sha256=context['base']['manifest_sha256'],snapshot_manifest_sha256=context['manifest_sha256'],
        green_context=dict(red=context['freeze']['red'],review=context['freeze']['test_review'],commit_sha=context['commit_sha']))
    encoded=json.dumps(request,sort_keys=True,separators=(',',':'));require(len(encoded.encode())<=65536)
    return dict(Image=delivery.image_id(b),User='10000:10000',Entrypoint=['python','/opt/quality/quality_green_job.py'],
        Cmd=[],WorkingDir='/tmp',NetworkDisabled=True,Env=['PYTHONDONTWRITEBYTECODE=1','QUALITY_GREEN_JOB_JSON='+encoded],
        Labels={'delivery-kit.quality-run':context['plan']['run_id'],'delivery-kit.quality-stage':'green-v2'},
        HostConfig=dict(ReadonlyRootfs=True,NetworkMode='none',CapDrop=['ALL'],SecurityOpt=['no-new-privileges'],
            Memory=268435456,NanoCpus=1000000000,PidsLimit=64,
            Tmpfs={'/tmp':'rw,nosuid,nodev,size=32m,mode=1777'},Mounts=[
                dict(Type='volume',Source=context['base']['volume'],Target='/base',ReadOnly=True),
                dict(Type='volume',Source=context['volume'],Target='/snapshot',ReadOnly=True)]))


def observed(b,context,result):
    p=grouped_create('POST','/containers/create?name=validation',context['payload'],b.PREFIX)
    task=context['task_id'];key=digest(dict(task=task,kind='green',payload=p))
    expected={**p,'Labels':{**p['Labels'],'delivery-kit.owner':b.OWNER,
        'delivery-kit.source-task':task,'delivery-kit.validation-job':key}}
    identity=dict(task=task,kind='green',name=b.PREFIX+'-validation-job-'+task+'-'+key[:12],payload=expected)
    with b.db() as con:row=con.execute('SELECT identity,state FROM validation_jobs WHERE job_key=?',(key,)).fetchone()
    require(row is not None and json.loads(row[0])==identity)
    state=json.loads(row[1])
    require(state.get('stage')=='complete' and state.get('result')==result
        and state.get('container_id')==result.get('container_id') and re.fullmatch('[a-f0-9]{64}',str(result.get('container_id')))
        and result.get('approval') is False and type(result.get('exit_code')) is int and result['exit_code']==0
        and result.get('validation_job_key')==key and result.get('validation_contract_sha256')==digest(identity)
        and isinstance(result.get('output'),str) and len(result['output'].encode())<=65536
        and result.get('output_sha256')==hashlib.sha256(result['output'].encode()).hexdigest())
    report=json.loads(result['output'])
    require(set(report)=={'operation','green','base_manifest_sha256','captured_output_sha256','captured_output_bytes',
            'snapshot_unchanged','commit_binding_verified','execution_authorized','delivery_approval'}
        and report['operation']=='full_suite_green_observation_v2' and report['snapshot_unchanged'] is True
        and report['commit_binding_verified'] is False and report['execution_authorized'] is False
        and report['delivery_approval'] is False and report['base_manifest_sha256']==context['base']['manifest_sha256']
        and type(report['captured_output_bytes']) is int and 0<=report['captured_output_bytes']<=1048576)
    quality.sha(report['captured_output_sha256'])
    green=report['green'];quality.green(context['plan'],context['freeze']['red'],context['freeze']['test_review'],green)
    require(green['commit_sha']==context['commit_sha'] and green['manifest_sha256']==context['manifest_sha256']
        and green['task_id']==task and green['tests']==context['freeze']['frozen_tests'])
    return dict(green=green,validation_job_key=key,validation_contract_sha256=digest(identity),
        container_id=result['container_id'],output_sha256=result['output_sha256'])


def observe(b,request):
    delivery.admission.enrollment.canonical(request)
    with delivery.red.observation_lock(b,request):
        old=load(b,request)
        if old and old[1]['stage'] in ('awaiting_sensitivity','technical_blocked'):return old[1]
        delivery.admission.enabled(b)
        if old:context,state=old
        else:
            context=provenance(b,request);context['payload']=payload(b,context)
            now=time.time();state=dict(stage='awaiting_green',owner=context['owner'],started_at=now,deadline=now+1800,
                observations=0,alert_due=False,execution_authorized=False,green_approved=False,delivery_approval=False)
            with b.LOCK,b.db() as con:
                maintenance.transaction(con)
                if maintenance.current(con):raise validation_job.Pending('maintenance pauses new Green observation')
                initialize(con)
                con.execute('INSERT INTO quality_green_captures VALUES(?,?,?,?,?)',
                    (request,json.dumps(context,sort_keys=True),json.dumps(state,sort_keys=True),quality.digest(context),quality.digest(state)))
        phase='green_source_provenance';deadline=state['deadline'];category='Pending'
        try:
            fresh=provenance(b,request);require({k:v for k,v in context.items() if k!='payload'}==fresh)
            with b.db() as con:
                if maintenance.current(con):raise validation_job.Pending('maintenance preserves original Green job')
                deadline=clock.deadline(con,b.PREFIX,state['deadline'],time.time(),budget=1800)
            state=save(b,request,context,state,{**state,'observations':state['observations']+1,
                'alert_due':time.time()>=deadline-1200})
            # A previously captured complete fixed job is evidence even after
            # downtime; validation_job itself owns deadlines for unfinished jobs.
            phase='green_fixed_job_receipt'
            result=validation_job.run(b,context['task_id'],'green',context['payload'])
            facts=observed(b,context,result)
            require(provenance(b,request)==fresh)
            return save(b,request,context,state,{**state,'stage':'awaiting_sensitivity','observation':facts,
                'next_action':'mandatory full-inventory negative controls before independent delivery review'})
        except validation_job.Pending as pending:
            if time.time()<deadline:
                pending.progress=state;raise
            phase='green_observation_deadline'
        except (TimeoutError,OSError) as error:
            pending=validation_job.Pending('observe original Green job and exact volume; no replay');pending.progress=state
            raise pending from error
        except (ValueError,KeyError,TypeError) as error:
            category=type(error).__name__
        return save(b,request,context,state,{**state,'stage':'technical_blocked','incident':dict(category=phase,
            error_type=category,automatic_retry=False,
            next_action='Tech Lead diagnose preserved Green/source evidence; escalate technical decisions to CTO')})
