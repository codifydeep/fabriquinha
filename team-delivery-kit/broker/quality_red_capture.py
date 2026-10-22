"""Controller-only v2 Red capture from authenticated native/copy/job records.

No raw report is accepted from a worker. No legacy calibration or historical
Red is converted. Slow evidence reads and Docker effects do not hold the global
admission lock/SQLite writer. A private per-source OS lock serializes observations
across processes; crash recovery still observes the durable validation job.
"""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from contextlib import contextmanager

from docker_grouping import grouped_create
try:
    from . import quality_lifecycle_enrollment as enrollment,quality_lifecycle_v2 as quality
    from . import native,validation_job
    from .test_first_job import digest
except ImportError:
    import quality_lifecycle_enrollment as enrollment
    import quality_lifecycle_v2 as quality
    import native,validation_job
    from test_first_job import digest


def require(condition):
    if not condition:raise ValueError('exact native v2 Red provenance required')


def initialize(con):
    # Only the future v2 admission adapter may populate this table while minting
    # a native capability. Creating the schema does not grant a phase to anyone.
    con.execute('CREATE TABLE IF NOT EXISTS quality_native_scopes('
        'request_id TEXT PRIMARY KEY,task_id TEXT,run_id TEXT,phase TEXT,plan_sha256 TEXT)')
    con.execute('CREATE TABLE IF NOT EXISTS quality_red_captures('
        'task_id TEXT PRIMARY KEY,issue_id TEXT,context TEXT,state TEXT,'
        'context_sha256 TEXT,state_sha256 TEXT)')


def source(con,task):
    require(enrollment.exists(con,'quality_native_scopes'))
    row=con.execute('SELECT n.request_id,n.task_id,n.agent_id,n.scope,n.issue_id,g.mode,g.used,g.attempt,l.status,q.run_id,q.plan_sha256 '
        'FROM native_bindings n JOIN grants g USING(request_id) JOIN leases l USING(request_id) '
        'JOIN quality_native_scopes q ON q.request_id=n.request_id AND q.task_id=n.task_id '
        "AND q.phase='tests_only_v2' "
        'WHERE n.task_id=? ORDER BY g.attempt DESC LIMIT 1',(task,)).fetchone()
    require(row is not None)
    value=dict(row);require(value['mode']=='implementation' and value['status']=='closed'
        and type(value['used']) is int and value['used']==1
        and type(value['attempt']) is int and value['attempt']>=1)
    require(con.execute('SELECT max(attempt) FROM grants WHERE task_id=?',(task,)).fetchone()[0]==value['attempt'])
    require(not con.execute("SELECT 1 FROM native_bindings n JOIN leases l USING(request_id) WHERE n.scope=? "
        "AND l.status IN ('creating','starting','running','closing')",(value['scope'],)).fetchone())
    return value


def copy_payload(b,e,task,binding):
    return dict(Image=copy_image_id(b),User='10000:10000',Entrypoint=['python'],Cmd=['/test_first_copy.py'],
        NetworkDisabled=True,Env=['TEST_FIRST_RESUME=0','TEST_FIRST_INCLUDE_INVENTORY=1'],
        Labels={'delivery-kit.owner':b.OWNER,'delivery-kit.test-first-task':task,'delivery-kit.quality-run':e['run_id']},
        HostConfig=dict(ReadonlyRootfs=True,NetworkMode='none',CapDrop=['ALL'],SecurityOpt=['no-new-privileges'],
            Memory=134217728,NanoCpus=500000000,PidsLimit=16,
            Tmpfs={'/tmp':'rw,nosuid,nodev,size=32m,mode=1777'},Mounts=[
                dict(Type='volume',Source=e['base_volume'],Target='/base',ReadOnly=True),
                dict(Type='volume',Source=b.PREFIX+'-work-'+hashlib.sha256(binding['scope'].encode()).hexdigest()[:32],
                    Target='/workspace',ReadOnly=True),
                dict(Type='volume',Source=b.PREFIX+'-quality-red-'+task,Target='/snapshot')]))


def copy_record(b,con,e,plan,spec,task,binding):
    row=con.execute('SELECT identity,state FROM test_first_jobs WHERE job_key=?',(task+':copy',)).fetchone()
    require(row is not None)
    identity,state=map(json.loads,row)
    name=b.PREFIX+'-test-first-copy-v2-'+task;payload=copy_payload(b,e,task,binding)
    payload=grouped_create('POST','/containers/create?name='+name,{**payload,'Labels':{**payload['Labels'],
        'delivery-kit.owner':b.OWNER,'delivery-kit.test-first-task':task,'delivery-kit.test-first-job':task+':copy'}},b.PREFIX)
    require(identity==dict(name=name,payload=payload) and state.get('stage')=='complete')
    result=state.get('result',{})
    require(type(result.get('exit_code')) is int and result.get('exit_code')==0 and result.get('approval') is False
        and bool(re.fullmatch('[a-f0-9]{64}',str(state.get('container_id'))))
        and result.get('container_id')==state['container_id']
        and isinstance(result.get('output'),str) and len(result['output'].encode())<=65536
        and result.get('output_sha256')==hashlib.sha256(result['output'].encode()).hexdigest())
    prepared=json.loads(result['output'])
    require(prepared.get('base_sha')==plan['base_sha']
        and prepared.get('base_manifest_sha256')==e['base_manifest_sha256']
        and prepared.get('baseline_test_sha256')==plan['baseline_tests']
        and set(prepared.get('test_sha256',{}))==set(plan['new_tests'])
        and prepared.get('command')==spec['test_command'] and prepared.get('test_roots')==spec['test_roots']
        and prepared.get('test_image')==spec['test_image']
        and bool(re.fullmatch('[a-f0-9]{64}',str(prepared.get('manifest_sha256')))))
    for sha in prepared['test_sha256'].values():require(bool(re.fullmatch('[a-f0-9]{64}',str(sha))))
    return dict(identity=identity,result=result,prepared=prepared)


def observer_payload(b,e,plan,task,prepared):
    request=dict(plan=plan,task_id=task,base_manifest_sha256=e['base_manifest_sha256'],
        snapshot_manifest_sha256=prepared['manifest_sha256'])
    encoded=json.dumps(request,sort_keys=True,separators=(',',':'))
    require(len(encoded.encode())<=65536)
    return dict(Image=b.QUALITY_RED_IMAGE,User='10000:10000',
        Entrypoint=['python','/opt/quality/quality_red_observation.py'],Cmd=[],WorkingDir='/tmp',
        NetworkDisabled=True,Env=['PYTHONDONTWRITEBYTECODE=1','QUALITY_RED_INPUT_JSON='+encoded],
        Labels={'delivery-kit.quality-run':e['run_id'],'delivery-kit.quality-stage':'red-v2'},
        HostConfig=dict(ReadonlyRootfs=True,NetworkMode='none',CapDrop=['ALL'],SecurityOpt=['no-new-privileges'],
            Memory=268435456,NanoCpus=1000000000,PidsLimit=64,
            Tmpfs={'/tmp':'rw,nosuid,nodev,size=32m,mode=1777'},Mounts=[
                dict(Type='volume',Source=e['base_volume'],Target='/base',ReadOnly=True),
                dict(Type='volume',Source=b.PREFIX+'-quality-red-'+task,Target='/snapshot',ReadOnly=True)]))


def job_identity(b,task,payload):
    payload=grouped_create('POST','/containers/create?name=validation',payload,b.PREFIX)
    key=digest(dict(task=task,kind='suite',payload=payload))
    name=b.PREFIX+'-validation-job-'+task+'-'+key[:12]
    expected={**payload,'Labels':{**payload['Labels'],'delivery-kit.owner':b.OWNER,
        'delivery-kit.source-task':task,'delivery-kit.validation-job':key}}
    return key,dict(task=task,kind='suite',name=name,payload=expected)


def authorize_source(b,task):
    """Read-only authority shared with the fixed snapshot producer."""
    with b.LOCK,b.db() as con:
        binding=source(con,task)
        e=enrollment.lookup(con,binding['issue_id']);require(e is not None and e['namespace']==b.PREFIX)
        require(binding['agent_id']==e['author'])
        plan,spec=enrollment.request(json.loads(con.execute('SELECT config FROM quality_lifecycle_enrollments '
            'WHERE issue_id=?',(e['issue_id'],)).fetchone()[0]))
        require(binding['run_id']==plan['run_id'] and binding['plan_sha256']==quality.digest(plan))
    settings=json.loads((b.STATE/'native.json').read_text())
    lead=getattr(b,'QUALITY_TECHLEAD',None);enrollment.canonical(lead)
    require(settings['workspace_id']==e['workspace_id'] and settings['runtime_id']==e['runtime_id']
        and settings['agents'].get(e['author'])=='implementation'
        and settings['agents'].get(e['reviewer'])=='review' and settings['agents'].get(lead)=='planning')
    observed=native.task_record(settings,task,e['author'])
    runs=[r for r in native.issue_task_runs(settings,e['issue_id']) if r.get('agent_id')==e['author']]
    require(observed.get('id')==task and observed.get('issue_id')==e['issue_id']
        and observed.get('agent_id')==e['author'] and observed.get('status')=='completed' and bool(runs)
        and max(runs,key=lambda r:(r.get('created_at') or '',r['id']))['id']==task)
    base=b.issue_base(e['issue_id'])
    require(base.get('issue_id')==e['issue_id'] and base.get('base_sha')==e['base_sha'] and base.get('volume')==e['base_volume']
        and base.get('manifest_sha256')==e['base_manifest_sha256'])
    workspace_name=b.PREFIX+'-work-'+hashlib.sha256(binding['scope'].encode()).hexdigest()[:32]
    workspace=b.docker('GET','/volumes/'+workspace_name) or {}
    require(workspace.get('Labels',{}).get('delivery-kit.owner')==b.OWNER
        and workspace.get('Labels',{}).get('delivery-kit.scope')==binding['scope'])
    copy_image=b.docker('GET','/images/'+copy_image_id(b)+'/json') or {}
    copy_config=copy_image.get('Config',{})
    require(copy_image.get('Id')==b.QUALITY_COPY_IMAGE and not copy_config.get('Volumes')
        and copy_config.get('Labels',{}).get('delivery-kit.component')=='quality-red-copy'
        and not any(re.search(r'token|secret|password|api.?key|credential|^aws_',str(v).split('=',1)[0],re.I)
            for v in copy_config.get('Env',[])))
    image=getattr(b,'QUALITY_RED_IMAGE',None)
    require(isinstance(image,str) and bool(re.fullmatch(r'sha256:[a-f0-9]{64}',image)))
    actual=b.docker('GET','/images/'+spec['test_image']+'/json') or {}
    cfg=actual.get('Config',{})
    require(actual.get('Id')==image and cfg.get('Labels',{}).get('delivery-kit.component')=='quality-red-observer'
        and cfg.get('Entrypoint')==['python','/opt/quality/quality_red_observation.py']
        and cfg.get('User')=='10000:10000' and not cfg.get('Volumes')
        and not any(re.search(r'token|secret|password|api.?key|credential|^aws_',str(v).split('=',1)[0],re.I)
            for v in cfg.get('Env',[])))
    return e,plan,spec,binding,lead


def prepare(b,task):
    e,plan,spec,binding,lead=authorize_source(b,task)
    with b.db() as con:copied=copy_record(b,con,e,plan,spec,task,binding)
    volume=b.PREFIX+'-quality-red-'+task
    snapshot=b.docker('GET','/volumes/'+volume) or {}
    labels=snapshot.get('Labels',{})
    require(labels.get('delivery-kit.owner')==b.OWNER and labels.get('delivery-kit.test-first-task')==task
        and labels.get('delivery-kit.quality-run')==e['run_id'])
    context=dict(enrollment_sha256=quality.digest(e),plan=plan,source=binding,copy=copied,
        reviewer=e['reviewer'],techlead=lead,payload=observer_payload(b,e,plan,task,copied['prepared']))
    state=dict(stage='validation_pending',owner=e['author'],execution_authorized=False,delivery_approval=False)
    with b.LOCK,b.db() as con:
        initialize(con)
        if not con.in_transaction:con.execute('BEGIN IMMEDIATE')
        require(source(con,task)==binding and quality.digest(enrollment.lookup(con,e['issue_id']))==context['enrollment_sha256'])
        prior=con.execute('SELECT context,state,context_sha256,state_sha256 FROM quality_red_captures '
            'WHERE task_id=?',(task,)).fetchone()
        if prior:
            require(json.loads(prior[0])==context and quality.digest(context)==prior[2]
                and quality.digest(json.loads(prior[1]))==prior[3])
            return context,json.loads(prior[1])
        con.execute('INSERT INTO quality_red_captures VALUES(?,?,?,?,?,?)',
            (task,e['issue_id'],json.dumps(context,sort_keys=True),json.dumps(state,sort_keys=True),
                quality.digest(context),quality.digest(state)))
    return context,state


def copy_image_id(b):
    image=getattr(b,'QUALITY_COPY_IMAGE',None)
    require(isinstance(image,str) and bool(re.fullmatch(r'sha256:[a-f0-9]{64}',image)))
    return image


@contextmanager
def observation_lock(b,task):
    path=b.STATE/'quality-red-locks'
    require(not path.is_symlink());path.mkdir(mode=0o700,exist_ok=True)
    fd=os.open(path/(task+'.lock'),os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    try:
        info=os.fstat(fd);require(stat.S_ISREG(info.st_mode) and info.st_nlink==1 and info.st_uid==os.getuid())
        try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise validation_job.Pending('same Red observation is already in progress') from None
        yield
    finally:os.close(fd)


def observe(b,task):
    enrollment.canonical(task)
    with observation_lock(b,task):
        try:return _observe(b,task)
        except (ValueError,KeyError,TypeError) as failure:
            # Preserve rejected evidence and the actual job key. No valid Red,
            # retry or release authority is manufactured by incident capture.
            with b.LOCK,b.db() as con:
                initialize(con)
                row=con.execute('SELECT context,state,context_sha256,state_sha256 FROM quality_red_captures '
                    'WHERE task_id=?',(task,)).fetchone()
                if row:
                    context,state=json.loads(row[0]),json.loads(row[1])
                    if (quality.digest(context)==row[2] and quality.digest(state)==row[3]
                            and state.get('stage')=='validation_pending'):
                        key,identity=job_identity(b,task,context['payload'])
                        blocked=dict(stage='technical_blocked',owner=context['techlead'],
                            provenance=dict(validation_job_key=key,validation_contract_sha256=digest(identity),
                                copy_sha256=quality.digest(context['copy']),enrollment_sha256=context['enrollment_sha256']),
                            incident=dict(category='red_provenance_rejected',source_task=task,automatic_retry=False,
                                next_action='Tech Lead inspect the preserved source/copy/job identity; no identical retry'),
                            execution_authorized=False,delivery_approval=False)
                        con.execute('UPDATE quality_red_captures SET state=?,state_sha256=? WHERE task_id=? AND state=?',
                            (json.dumps(blocked,sort_keys=True),quality.digest(blocked),task,row[1]))
            raise ValueError('v2 Red evidence rejected; inspect preserved controller records') from failure


def _observe(b,task):
    with b.db() as con:
        initialize(con)
        row=con.execute('SELECT issue_id,context,state,context_sha256,state_sha256 FROM quality_red_captures '
            'WHERE task_id=?',(task,)).fetchone()
        if row:
            issue,raw,state=row[0],row[1],json.loads(row[2]);context=json.loads(raw)
            require(quality.digest(context)==row[3] and quality.digest(state)==row[4]
                and state.get('stage') in ('validation_pending','awaiting_independent_test_review','technical_blocked')
                and state.get('execution_authorized') is False and state.get('delivery_approval') is False
                and quality.digest(enrollment.lookup(con,issue))==context['enrollment_sha256'])
            if state['stage']!='validation_pending':return state
            require(source(con,task)==context['source'])
    if not row:context,state=prepare(b,task)
    result=validation_job.run(b,task,'suite',context['payload'])
    key,identity=job_identity(b,task,context['payload'])
    with b.db() as con:
        job=con.execute('SELECT identity,state FROM validation_jobs WHERE job_key=?',(key,)).fetchone()
        require(job is not None and json.loads(job[0])==identity)
        saved=json.loads(job[1])
        require(saved.get('stage')=='complete' and saved.get('result')==result
            and type(result.get('exit_code')) is int
            and result.get('container_id')==saved.get('container_id')
            and bool(re.fullmatch('[a-f0-9]{64}',str(result.get('container_id'))))
            and result.get('validation_job_key')==key and result.get('validation_contract_sha256')==digest(identity)
            and result.get('approval') is False and isinstance(result.get('output'),str)
            and len(result['output'].encode())<=1048576
            and result.get('output_sha256')==hashlib.sha256(result['output'].encode()).hexdigest())
    report=json.loads(result['output'])
    require(isinstance(report,dict))
    provenance=dict(validation_job_key=key,validation_contract_sha256=digest(identity),
        copy_sha256=quality.digest(context['copy']),enrollment_sha256=context['enrollment_sha256'])
    if result['exit_code']==0:
        plan=context['plan'];quality.red(plan,report['red'])
        require(set(report)=={'operation','red','base_manifest_sha256','captured_output_sha256',
                'captured_output_bytes','snapshot_unchanged','execution_authorized','delivery_approval'}
            and report.get('operation')=='full_suite_red_observation_v2'
            and isinstance(report.get('captured_output_sha256'),str)
            and bool(re.fullmatch('[a-f0-9]{64}',report['captured_output_sha256']))
            and type(report.get('captured_output_bytes')) is int and 0<=report['captured_output_bytes']<2**63
            and report.get('execution_authorized') is False and report.get('delivery_approval') is False
            and report.get('snapshot_unchanged') is True and report['red']['task_id']==task
            and report['red']['manifest_sha256']==context['copy']['prepared']['manifest_sha256']
            and report['red']['tests']=={**plan['baseline_tests'],**context['copy']['prepared']['test_sha256']}
            and report.get('base_manifest_sha256')==context['copy']['prepared']['base_manifest_sha256'])
        state=dict(stage='awaiting_independent_test_review',owner=context['reviewer'],red=report['red'],
            provenance=provenance,execution_authorized=False,delivery_approval=False)
    else:
        require(set(report)=={'operation','category','execution_authorized','delivery_approval'}
            and result['exit_code']==2 and report.get('operation')=='rejected_red_observation_v2'
            and report.get('execution_authorized') is False and report.get('delivery_approval') is False
            and isinstance(report.get('category'),str) and bool(re.fullmatch('[A-Za-z0-9_]{1,100}',report['category'])))
        state=dict(stage='technical_blocked',owner=context['techlead'],provenance=provenance,
            incident=dict(category=report['category'],source_task=task,automatic_retry=False,
                next_action='Tech Lead diagnose the frozen Red evidence; do not repeat the same execution'),
            execution_authorized=False,delivery_approval=False)
    with b.LOCK,b.db() as con:
        require(source(con,task)==context['source'] and quality.digest(enrollment.lookup(con,context['plan']['issue_id']))==context['enrollment_sha256'])
        changed=con.execute('UPDATE quality_red_captures SET state=?,state_sha256=? WHERE task_id=? AND context=? AND state=?',
            (json.dumps(state,sort_keys=True),quality.digest(state),task,json.dumps(context,sort_keys=True),
                json.dumps(dict(stage='validation_pending',owner=context['source']['agent_id'],
                    execution_authorized=False,delivery_approval=False),sort_keys=True)))
        require(changed.rowcount==1)
    return state
