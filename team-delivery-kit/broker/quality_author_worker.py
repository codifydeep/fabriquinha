"""Durable v2 workspace seed/lock before any worker or model starts.

No route-dependent legacy permissions, implicit volume adoption or arbitrary
commands. Launch still requires a separate current-native/capability check.
"""
import hashlib
import json
import re
import time
from docker_grouping import grouped_create
try:
    from . import quality_author_admission as admission,quality_red_capture as capture
    from . import controller_maintenance as maintenance,validation_job,native
    from .test_first_job import digest
except ImportError:
    import quality_author_admission as admission,quality_red_capture as capture
    import controller_maintenance as maintenance,validation_job,native
    from test_first_job import digest

require=admission.require


def initialize(con):
    con.execute('CREATE TABLE IF NOT EXISTS quality_author_workspaces('
        'request_id TEXT PRIMARY KEY,context TEXT,state TEXT,context_sha256 TEXT,state_sha256 TEXT)')


def save(b,request,c,before,after):
    with b.LOCK,b.db() as con:
        changed=con.execute('UPDATE quality_author_workspaces SET state=?,state_sha256=? '
            'WHERE request_id=? AND context_sha256=? AND state_sha256=?',
            (json.dumps(after,sort_keys=True),admission.quality.digest(after),request,
                admission.quality.digest(c),admission.quality.digest(before)))
        require(changed.rowcount==1)
    return after


def payload(b,c,phase):
    require(phase in ('seed','lock'))
    image=getattr(b,'QUALITY_PREP_IMAGE',None)
    require(isinstance(image,str) and re.fullmatch('sha256:[a-f0-9]{64}',image))
    root=phase=='lock'
    env=(['WORKSPACE_ALLOWED_JSON='+json.dumps([p.removeprefix('/workspace/')
        for p in c['selection']['editable_paths']])] if root else
        ['BASE_MANIFEST_SHA256='+c['selection']['base']['manifest_sha256']])
    host=dict(ReadonlyRootfs=True,NetworkMode='none',CapDrop=['ALL'],SecurityOpt=['no-new-privileges'],
        Memory=134217728,NanoCpus=500000000,PidsLimit=16,
        Tmpfs={'/tmp':'rw,nosuid,nodev,size=32m,mode=1777'},Mounts=[
            dict(Type='volume',Source=c['selection']['base']['volume'],Target='/base',ReadOnly=True),
            dict(Type='volume',Source=c['volume'],Target='/workspace')])
    selected=c['selection']
    require(selected['phase']==c['source']['phase'] and selected['phase'] in ('tests_only_v2','implementation_v2'))
    if selected['phase']=='implementation_v2':
        frozen=selected['frozen_seed']
        require(isinstance(frozen,dict) and set(frozen)=={'volume','manifest_sha256','test_sha256'}
            and re.fullmatch('[A-Za-z0-9_.-]{1,200}',str(frozen['volume']))
            and re.fullmatch('[a-f0-9]{64}',str(frozen['manifest_sha256']))
            and isinstance(frozen['test_sha256'],dict) and bool(frozen['test_sha256'])
            and not set(frozen['test_sha256'])&{p.removeprefix('/workspace/') for p in selected['editable_paths']})
        if not root:
            env+=['REVISION_SEED_JSON='+json.dumps({k:v for k,v in frozen.items() if k!='volume'})]
            host['Mounts'].append(dict(Type='volume',Source=frozen['volume'],Target='/previous',ReadOnly=True))
    else:require('frozen_seed' not in selected)
    if root:host['CapAdd']=['CHOWN','DAC_OVERRIDE']
    return dict(Image=image,User='0:0' if root else '10000:10000',Entrypoint=['python'],
        Cmd=['/workspace_lockdown.py' if root else '/seed_workspace.py'],NetworkDisabled=True,Env=env,
        Labels={'delivery-kit.owner':b.OWNER,'delivery-kit.source-task':c['source']['task_id'],
            'delivery-kit.quality-run':c['source']['run_id']},HostConfig=host)


def executed(b,c,phase):
    kind='scope_materialize' if phase=='seed' else 'scope_base_verify'
    supplied=payload(b,c,phase);task=c['source']['task_id']
    result=validation_job.run(b,task,kind,supplied)
    normalized=grouped_create('POST','/containers/create?name=validation',supplied,b.PREFIX)
    key=digest(dict(task=task,kind=kind,payload=normalized))
    expected={**normalized,'Labels':{**normalized['Labels'],'delivery-kit.owner':b.OWNER,
        'delivery-kit.source-task':task,'delivery-kit.validation-job':key}}
    identity=dict(task=task,kind=kind,name=b.PREFIX+'-validation-job-'+task+'-'+key[:12],payload=expected)
    with b.db() as con:
        row=con.execute('SELECT identity,state FROM validation_jobs WHERE job_key=?',(key,)).fetchone()
    require(row is not None and json.loads(row[0])==identity)
    state=json.loads(row[1])
    require(state.get('stage')=='complete' and state.get('result')==result
        and result.get('approval') is False and type(result.get('exit_code')) is int and result['exit_code']==0
        and re.fullmatch('[a-f0-9]{64}',str(result.get('container_id')))
        and state.get('container_id')==result['container_id']
        and result.get('validation_job_key')==key and result.get('validation_contract_sha256')==digest(identity)
        and isinstance(result.get('output'),str) and len(result['output'].encode())<=65536
        and result.get('output_sha256')==hashlib.sha256(result['output'].encode()).hexdigest())
    if phase=='seed':require(result['output']=='')
    else:
        report=json.loads(result['output'])
        require(set(report)=={'allowed','baseline_files'}
            and report['allowed']==sorted(p.removeprefix('/workspace/') for p in c['selection']['editable_paths'])
            and type(report['baseline_files']) is int and report['baseline_files']>=1)
    return dict(job_key=key,result_sha256=admission.quality.digest(result),container_id=result['container_id'])


def prepare(b,request_id,*,now=None,admission_adapter=None):
    admission.enrollment.canonical(request_id)
    authority=admission_adapter or admission
    with b.db() as con:
        source=authority.load(con,request_id);require(source is not None)
    # All preparation and source observation serialize by the actual source task.
    with capture.observation_lock(b,source['task_id']):
        return _prepare(b,request_id,source,time.time() if now is None else now,authority)


def _prepare(b,request_id,source,now,authority=None):
    authority=authority or admission
    selected=authority.selection(b,request_id)
    volume=b.PREFIX+'-work-'+hashlib.sha256(source['scope'].encode()).hexdigest()[:32]
    labels={'delivery-kit.owner':b.OWNER,'delivery-kit.scope':source['scope'],
        'delivery-kit.quality-run':source['run_id'],'delivery-kit.lifecycle':'workspace',
        'com.docker.compose.project':b.PREFIX+'-tests','com.docker.compose.volume':'quality-author-workspace'}
    c=dict(source=source,selection=selected,volume=volume,labels=labels,prep_image=getattr(b,'QUALITY_PREP_IMAGE',None))
    with b.db() as con:
        initialize(con)
        row=con.execute('SELECT context,state,context_sha256,state_sha256 FROM quality_author_workspaces WHERE request_id=?',
            (request_id,)).fetchone()
        if row:
            prior,state=json.loads(row[0]),json.loads(row[1])
            require(prior==c and admission.quality.digest(prior)==row[2] and admission.quality.digest(state)==row[3])
            require(state['stage'] in ('prepared','volume_create_intent','seed_pending','lock_pending','workspace_locked'))
            if state['stage']=='workspace_locked':return state
        if maintenance.current(con):raise validation_job.Pending('maintenance pauses v2 workspace preparation')
        grant=con.execute('SELECT used,deadline FROM grants WHERE request_id=?',(request_id,)).fetchone()
        require(grant is not None and grant['used']==0 and grant['deadline']>now
            and not con.execute('SELECT 1 FROM leases WHERE request_id=?',(request_id,)).fetchone())
    settings=json.loads((b.STATE/'native.json').read_text())
    with b.db() as con:e=authority.enrollment.lookup(con,source['issue_id'])
    require(e is not None and settings['workspace_id']==e['workspace_id']
        and settings['runtime_id']==e['runtime_id'] and settings['agents'].get(source['agent_id'])=='implementation')
    observed=native.task_record(settings,source['task_id'],source['agent_id'])
    require(observed.get('id')==source['task_id'] and observed.get('issue_id')==source['issue_id']
        and observed.get('agent_id')==source['agent_id'] and observed.get('status')=='running'
        and observed.get('workspace_id')==settings['workspace_id'] and observed.get('runtime_id')==settings['runtime_id'])
    image=b.docker('GET','/images/'+str(c['prep_image'])+'/json') or {};config=image.get('Config',{})
    require(image.get('Id')==c['prep_image'] and not config.get('Volumes')
        and config.get('Labels',{}).get('delivery-kit.component')=='quality-author-prep'
        and config.get('User')=='10000:10000' and config.get('Entrypoint')==['python']
        and not any(re.search(r'token|secret|password|api.?key|credential|^aws_',str(v).split('=',1)[0],re.I)
            for v in config.get('Env',[])))
    payload(b,c,'seed')  # Validate immutable image ID before persisting any intent.
    if not row:
        state=dict(stage='prepared',owner=source['agent_id'],worker_launch_authorized=False,delivery_approval=False)
        with b.LOCK,b.db() as con:
            maintenance.require_admission(con)
            require(authority.load(con,request_id)==source)
            con.execute('INSERT INTO quality_author_workspaces VALUES(?,?,?,?,?)',
                (request_id,json.dumps(c,sort_keys=True),json.dumps(state,sort_keys=True),
                    admission.quality.digest(c),admission.quality.digest(state)))
    if state['stage']=='prepared':
        require(b.docker('GET','/volumes/'+volume) is None)
        state=save(b,request_id,c,state,{**state,'stage':'volume_create_intent'})
        try:b.docker('POST','/volumes/create',dict(Name=volume,Driver='local',Labels=labels))
        except TimeoutError:raise validation_job.Pending('observe original workspace volume; no repeated POST') from None
    info=b.docker('GET','/volumes/'+volume)
    if info is None:raise validation_job.Pending('observe original workspace volume creation')
    identity=capture.quality.digest(capture_identity(info,c))
    if state['stage']=='volume_create_intent':
        state=save(b,request_id,c,state,{**state,'stage':'seed_pending','volume_identity_sha256':identity})
    require(state['volume_identity_sha256']==identity)
    for phase,expected,next_stage in [('seed','seed_pending','lock_pending'),('lock','lock_pending','workspace_locked')]:
        if state['stage']==expected:
            with b.db() as con:
                if maintenance.current(con):raise validation_job.Pending('maintenance pauses fixed workspace jobs')
            receipt=executed(b,c,phase)
            state=save(b,request_id,c,state,{**state,'stage':next_stage,phase:receipt})
    return state


def capture_identity(info,c):
    require(info.get('Name')==c['volume'] and info.get('Driver')=='local' and info.get('Scope')=='local'
        and info.get('Labels')==c['labels'] and info.get('Options') in (None,{})
        and isinstance(info.get('CreatedAt'),str) and 1<=len(info['CreatedAt'])<=100)
    return {k:info[k] for k in ('Name','Driver','Scope','Labels','CreatedAt')}
