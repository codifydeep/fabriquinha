"""Controller-attested fixed full-suite validation for an admitted reviewer.

Default off with the native handoff. Reauthenticates before/after the fixed job
and captures its durable exact-payload receipt. This is evidence, never a
verdict, merge grant or release approval; worker launch/verdict routing is not
installed yet. No worker-supplied command, test subset or writable snapshot.
"""
import json
import re
import time
try:
    from . import quality_delivery_review_handoff as handoff,quality_green_capture as green
    from . import controller_maintenance as maintenance,maintenance_job_clock as clock,validation_job
except ImportError:
    import quality_delivery_review_handoff as handoff,quality_green_capture as green
    import controller_maintenance as maintenance,maintenance_job_clock as clock,validation_job

quality=handoff.quality
require=handoff.require


def initialize(con):
    con.execute('CREATE TABLE IF NOT EXISTS quality_delivery_review_validations('
        'request_id TEXT PRIMARY KEY,context TEXT,state TEXT,context_sha256 TEXT,state_sha256 TEXT)')


def load(b,request):
    with b.db() as con:
        initialize(con)
        row=con.execute('SELECT context,state,context_sha256,state_sha256 FROM quality_delivery_review_validations '
            'WHERE request_id=?',(request,)).fetchone()
        if row is None:return None
        context,state=json.loads(row[0]),json.loads(row[1])
        require(quality.digest(context)==row[2] and quality.digest(state)==row[3]
            and context['namespace']==b.PREFIX and context['request_id']==request
            and state['stage'] in ('awaiting_review_validation','review_validation_observed','technical_blocked')
            and all(state.get(k) is False for k in ('execution_authorized','merge_authorized','delivery_approval')))
        c=handoff.admission(con,request)
        require(c is not None and quality.digest(c)==context['admission_sha256'])
    return context,state


def provenance(b,request):
    c,assignment=handoff.current(b,request)
    return dict(namespace=b.PREFIX,request_id=request,task_id=c['task_id'],reviewer=c['agent_id'],
        implementation_request=c['implementation_request'],admission_sha256=quality.digest(c),
        assignment_sha256=quality.digest(assignment),plan=assignment['plan'],evidence=assignment['evidence'],
        base=assignment['base'],snapshot=assignment['snapshot'],manifest_sha256=c['manifest_sha256'],commit_sha=c['commit_sha'],
        owner=assignment['cto'])


def payload(b,context):
    image=getattr(b,'QUALITY_DELIVERY_REVIEW_JOB_IMAGE',None)
    require(isinstance(image,str) and re.fullmatch('sha256:[a-f0-9]{64}',image))
    actual=b.docker('GET','/images/'+image+'/json') or {};config=actual.get('Config',{})
    require(actual.get('Id')==image and config.get('User')=='10000:10000' and not config.get('Volumes')
        and config.get('Entrypoint')==['python','/opt/quality/quality_delivery_review_job.py']
        and config.get('Labels',{}).get('delivery-kit.component')=='quality-delivery-review-job'
        and config.get('Labels',{}).get('delivery-kit.quality-operations')=='validate_delivery_review_v2'
        and not any(re.search(r'token|secret|password|api.?key|credential|^aws_',str(v).split('=',1)[0],re.I)
            for v in config.get('Env',[])))
    value=dict(operation='validate_delivery_review_v2',plan=context['plan'],evidence=context['evidence'],
        task_id=context['task_id'],request_id=context['request_id'],reviewer=context['reviewer'],
        base_manifest_sha256=context['base']['manifest_sha256'],snapshot_manifest_sha256=context['manifest_sha256'])
    encoded=json.dumps(value,sort_keys=True,separators=(',',':'));require(len(encoded.encode())<=65536)
    return dict(Image=image,User='10000:10000',Entrypoint=['python','/opt/quality/quality_delivery_review_job.py'],
        Cmd=[],WorkingDir='/tmp',NetworkDisabled=True,
        Env=['PYTHONDONTWRITEBYTECODE=1','QUALITY_DELIVERY_REVIEW_JOB_JSON='+encoded],
        Labels={'delivery-kit.quality-run':context['plan']['run_id'],'delivery-kit.quality-stage':'delivery-review-validation-v2'},
        HostConfig=dict(ReadonlyRootfs=True,NetworkMode='none',CapDrop=['ALL'],SecurityOpt=['no-new-privileges'],
            Memory=268435456,NanoCpus=1000000000,PidsLimit=64,AutoRemove=False,Privileged=False,Binds=[],VolumesFrom=[],
            Tmpfs={'/tmp':'rw,nosuid,nodev,size=32m,mode=1777'},Mounts=[
                dict(Type='volume',Source=context['base']['volume'],Target='/base',ReadOnly=True),
                dict(Type='volume',Source=context['snapshot']['volume'],Target='/snapshot',ReadOnly=True)]))


def observed(b,context,result):
    receipt=green.fixed_receipt(b,context['task_id'],'delivery_review',context['payload'],result)
    report=json.loads(result['output']);plan=context['plan'];passing=context['evidence']['green']
    expected=dict(operation='full_suite_delivery_review_observation_v2',run_id=plan['run_id'],issue_id=plan['issue_id'],
        contract_sha256=plan['contract_sha256'],plan_sha256=quality.digest(plan),task_id=context['task_id'],
        request_id=context['request_id'],reviewer=context['reviewer'],quality_evidence_sha256=quality.digest(context['evidence']),
        base_manifest_sha256=context['base']['manifest_sha256'],manifest_sha256=context['manifest_sha256'],commit_sha=context['commit_sha'],
        snapshot_unchanged=True,native_identity_verified=False,job_receipt_verified=False,tests_approved=False,
        merge_authorized=False,delivery_approval=False)
    require(isinstance(report,dict) and set(report)==set(expected)|{'suite','captured_output_sha256','captured_output_bytes'})
    for key,value in expected.items():require(type(report[key]) is type(value) and report[key]==value)
    quality.sha(report['captured_output_sha256'])
    require(type(report['captured_output_bytes']) is int and 0<=report['captured_output_bytes']<=1048576
        and isinstance(report['suite'],dict) and set(report['suite'])==quality.suite_fields(plan)
        and report['suite']['tests_run']==passing['tests_run'])
    quality.suite(plan,report['suite'],passing=True,minimum=passing['tests_run'],frozen=passing['tests'],
        node_manifest=context['manifest_sha256'],frozen_node=passing.get('node_baseline'))
    facts=dict(operation='observed_delivery_review_validation_v2',run_id=plan['run_id'],issue_id=plan['issue_id'],
        contract_sha256=plan['contract_sha256'],plan_sha256=quality.digest(plan),task_id=context['task_id'],
        request_id=context['request_id'],reviewer=context['reviewer'],quality_evidence_sha256=quality.digest(context['evidence']),
        manifest_sha256=context['manifest_sha256'],commit_sha=context['commit_sha'],job_receipt_sha256=quality.digest(receipt),
        network='none',snapshot_mount='readonly',**report['suite'])
    return facts,receipt


def save(b,request,context,before,after):
    with b.LOCK,b.db() as con:
        maintenance.transaction(con)
        if maintenance.current(con):raise validation_job.Pending('maintenance preserves review validation')
        changed=con.execute('UPDATE quality_delivery_review_validations SET state=?,state_sha256=? '
            'WHERE request_id=? AND context_sha256=? AND state_sha256=?',
            (json.dumps(after,sort_keys=True),quality.digest(after),request,quality.digest(context),quality.digest(before)))
        require(changed.rowcount==1)
    return after


def observe(b,request):
    handoff.enabled(b);handoff.enrollment.canonical(request)
    with handoff.delivery.red.observation_lock(b,request):
        with b.db() as con:
            if maintenance.current(con):raise validation_job.Pending('maintenance preserves review validation')
        old=load(b,request)
        if old and old[1]['stage'] in ('review_validation_observed','technical_blocked'):return old[1]
        if old:context,state=old
        else:
            context=provenance(b,request);context['payload']=payload(b,context)
            now=time.time();state=dict(stage='awaiting_review_validation',owner=context['owner'],deadline=now+1800,
                observations=0,alert_due=False,execution_authorized=False,merge_authorized=False,delivery_approval=False)
            with b.LOCK,b.db() as con:
                maintenance.transaction(con)
                if maintenance.current(con):raise validation_job.Pending('maintenance pauses review validation registration')
                require(quality.digest(handoff.admission(con,request))==context['admission_sha256'])
                initialize(con);con.execute('INSERT INTO quality_delivery_review_validations VALUES(?,?,?,?,?)',
                    (request,json.dumps(context,sort_keys=True),json.dumps(state,sort_keys=True),quality.digest(context),quality.digest(state)))
        phase='delivery_review_source_provenance';deadline=state['deadline'];category='Pending'
        try:
            fresh=provenance(b,request);require(fresh=={k:v for k,v in context.items() if k!='payload'})
            with b.db() as con:deadline=clock.deadline(con,b.PREFIX,state['deadline'],time.time(),budget=1800)
            state=save(b,request,context,state,{**state,'observations':state['observations']+1,'alert_due':time.time()>=deadline-1200})
            phase='delivery_review_fixed_job_receipt'
            result=validation_job.run(b,context['task_id'],'delivery_review',context['payload'])
            facts,receipt=observed(b,context,result);require(provenance(b,request)==fresh)
            return save(b,request,context,state,{**state,'stage':'review_validation_observed','validation':facts,
                'job_receipt':receipt,'next_action':'reviewer must inspect exact delivery and issue its own independent verdict'})
        except validation_job.Pending as pending:
            if time.time()<deadline:pending.progress=state;raise
            phase='delivery_review_observation_deadline'
        except (TimeoutError,OSError) as error:
            if time.time()<deadline:
                pending=validation_job.Pending('observe same review validation and native execution; never replay');pending.progress=state
                raise pending from error
            phase='delivery_review_source_observation_deadline';category=type(error).__name__
        except (ValueError,KeyError,TypeError) as error:category=type(error).__name__
        return save(b,request,context,state,{**state,'stage':'technical_blocked',
            'incident':dict(category=phase,error_type=category,automatic_retry=False,
                next_action='CTO diagnose original review validation/native evidence; no same-condition retry or gate waiver')})
