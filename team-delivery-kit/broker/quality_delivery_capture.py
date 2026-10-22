"""Controller journal for the completed Green author's immutable delivery copy.

Authenticates native task, ACP, closed lease, inspected worker and locked volume.
Unknown Docker/job acknowledgments observe the original handles. Snapshot
capture alone grants neither Git binding nor Green, review, merge or delivery.
"""
import hashlib
import json
import re
import time
from docker_grouping import grouped_create
try:
    from . import quality_implementation_admission as admission,quality_implementation_launch as launch
    from . import quality_red_capture as red,quality_author_worker as workspace,native,validation_job
    from . import controller_maintenance as maintenance,maintenance_job_clock as clock,worker_creation_intent as worker
    from .test_first_job import digest
except ImportError:
    import quality_implementation_admission as admission,quality_implementation_launch as launch
    import quality_red_capture as red,quality_author_worker as workspace,native,validation_job
    import controller_maintenance as maintenance,maintenance_job_clock as clock,worker_creation_intent as worker
    from test_first_job import digest

require=admission.require
quality=admission.quality
STAGES={'awaiting_author_completion','volume_create_intent','copy_pending','awaiting_git_binding','technical_blocked'}


def initialize(con):
    con.execute('CREATE TABLE IF NOT EXISTS quality_delivery_captures('
        'request_id TEXT PRIMARY KEY,context TEXT,state TEXT,context_sha256 TEXT,state_sha256 TEXT)')


def load(b,request):
    with b.db() as con:
        initialize(con)
        row=con.execute('SELECT context,state,context_sha256,state_sha256 FROM quality_delivery_captures '
            'WHERE request_id=?',(request,)).fetchone()
    if not row:return None
    context,state=json.loads(row[0]),json.loads(row[1])
    require(quality.digest(context)==row[2] and quality.digest(state)==row[3]
        and context['namespace']==b.PREFIX and context['admission']['request_id']==request
        and state['stage'] in STAGES and all(state.get(k) is False for k in
            ('execution_authorized','green_approved','delivery_approval')))
    return context,state


def save(b,request,context,before,after):
    with b.LOCK,b.db() as con:
        maintenance.transaction(con)
        if maintenance.current(con):raise validation_job.Pending('maintenance preserves original delivery capture')
        changed=con.execute('UPDATE quality_delivery_captures SET state=?,state_sha256=? '
            'WHERE request_id=? AND context_sha256=? AND state_sha256=?',
            (json.dumps(after,sort_keys=True),quality.digest(after),request,quality.digest(context),quality.digest(before)))
        require(changed.rowcount==1)
    return after


def image_id(b):
    image=getattr(b,'QUALITY_GREEN_JOB_IMAGE',None)
    require(isinstance(image,str) and re.fullmatch('sha256:[a-f0-9]{64}',image))
    actual=b.docker('GET','/images/'+image+'/json') or {};cfg=actual.get('Config',{})
    require(actual.get('Id')==image and cfg.get('User')=='10000:10000' and not cfg.get('Volumes')
        and cfg.get('Entrypoint')==['python','/opt/quality/quality_green_job.py']
        and cfg.get('Labels',{}).get('delivery-kit.component')=='quality-green-job'
        and not any(re.search(r'token|secret|password|api.?key|credential|^aws_',str(v).split('=',1)[0],re.I)
            for v in cfg.get('Env',[])))
    return image


def copy_payload(b,context):
    frozen=context['freeze'];evidence=dict(operation='snapshot_after_implementation_v2',plan=frozen['plan'],
        base_manifest_sha256=context['base']['manifest_sha256'],reviewed_manifest_sha256=frozen['manifest_sha256'],
        frozen_tests=frozen['frozen_tests'])
    encoded=json.dumps(evidence,sort_keys=True,separators=(',',':'));require(len(encoded.encode())<=65536)
    return dict(Image=context['image'],User='10000:10000',Entrypoint=['python','/opt/quality/quality_green_job.py'],
        Cmd=[],WorkingDir='/tmp',NetworkDisabled=True,Env=['PYTHONDONTWRITEBYTECODE=1','QUALITY_GREEN_JOB_JSON='+encoded],
        Labels={'delivery-kit.quality-run':context['admission']['run_id'],'delivery-kit.quality-stage':'delivery-copy-v2'},
        HostConfig=dict(ReadonlyRootfs=True,NetworkMode='none',CapDrop=['ALL'],SecurityOpt=['no-new-privileges'],
            Memory=134217728,NanoCpus=500000000,PidsLimit=16,Tmpfs={'/tmp':'rw,nosuid,nodev,size=32m,mode=1777'},
            Mounts=[dict(Type='volume',Source=context['base']['volume'],Target='/base',ReadOnly=True),
                dict(Type='volume',Source=context['reviewed_snapshot']['volume'],Target='/reviewed',ReadOnly=True),
                dict(Type='volume',Source=context['workspace'],Target='/workspace',ReadOnly=True),
                dict(Type='volume',Source=context['name'],Target='/snapshot')]))


def register(b,request):
    admission.enabled(b)
    with b.db() as con:c=admission.load(con,request);require(c is not None and c['namespace']==b.PREFIX)
    handoff,_=admission.handoff(b,c['source_task']);frozen,e=admission.frozen(b,c['source_task'])
    require(quality.digest(handoff)==c['handoff_sha256'] and quality.digest(frozen)==c['frozen_sha256'])
    reviewed=admission.snapshot_identity(b,c['source_task'],frozen['manifest_sha256'])
    require(reviewed==handoff['snapshot'] and b.issue_base(c['issue_id'])==handoff['base'])
    with b.db() as con:
        row=con.execute('SELECT context,context_sha256 FROM quality_red_captures WHERE task_id=?',(c['source_task'],)).fetchone()
    require(row is not None and quality.digest(json.loads(row[0]))==row[1])
    original=json.loads(row[0]);prepared=original['copy']['prepared']
    inventory=prepared['file_inventory']
    require(original['plan']==frozen['plan'] and prepared['manifest_sha256']==frozen['manifest_sha256']
        and hashlib.sha256(json.dumps(dict(files=inventory),sort_keys=True,separators=(',',':')).encode()).hexdigest()==frozen['manifest_sha256'])
    name=b.PREFIX+'-quality-delivery-'+c['task_id']
    labels={'delivery-kit.owner':b.OWNER,'delivery-kit.source-task':c['task_id'],'delivery-kit.quality-run':c['run_id'],
        'delivery-kit.lifecycle':'snapshot','com.docker.compose.project':b.PREFIX+'-tests',
        'com.docker.compose.volume':'quality-delivery-snapshot'}
    context=dict(namespace=b.PREFIX,admission=c,handoff_sha256=quality.digest(handoff),freeze=frozen,
        enrollment_sha256=quality.digest(e),base=handoff['base'],reviewed_snapshot=reviewed,
        reviewed_inventory=inventory,techlead=handoff['techlead'],cto=handoff['cto'],requirements=handoff['requirements'],
        workspace=b.PREFIX+'-work-'+hashlib.sha256(c['scope'].encode()).hexdigest()[:32],
        image=image_id(b),name=name,labels=labels)
    context['payload']=copy_payload(b,context)
    now=time.time();state=dict(stage='awaiting_author_completion',owner=c['agent_id'],started_at=now,deadline=now+1800,
        observations=0,alert_due=False,execution_authorized=False,green_approved=False,delivery_approval=False)
    with b.LOCK,b.db() as con:
        maintenance.transaction(con)
        if maintenance.current(con):raise validation_job.Pending('maintenance pauses new delivery capture')
        require(admission.load(con,request)==c)
        con.execute('INSERT INTO quality_delivery_captures VALUES(?,?,?,?,?)',
            (request,json.dumps(context,sort_keys=True),json.dumps(state,sort_keys=True),quality.digest(context),quality.digest(state)))
    return context,state


def completed_source(b,context):
    c=context['admission'];request=c['request_id']
    with b.db() as con:require(admission.load(con,request)==c)
    frozen,e=admission.frozen(b,c['source_task']);require(frozen==context['freeze'])
    handoff,assignment=admission.handoff(b,c['source_task'])
    require(quality.digest(handoff)==context['handoff_sha256'] and assignment['stage']=='admitted'
        and assignment['request_id']==request and assignment['task_id']==c['task_id']
        and quality.digest(e)==context['enrollment_sha256'] and b.issue_base(c['issue_id'])==context['base']
        and admission.snapshot_identity(b,c['source_task'],frozen['manifest_sha256'])==context['reviewed_snapshot'])
    settings=json.loads((b.STATE/'native.json').read_text())
    require(settings['workspace_id']==e['workspace_id'] and settings['runtime_id']==e['runtime_id']
        and settings['agents'].get(c['agent_id'])=='implementation'
        and settings['agents'].get(context['techlead'])=='planning')
    task=native.task_record(settings,c['task_id'],c['agent_id'])
    require(task.get('id')==c['task_id'] and task.get('agent_id')==c['agent_id'] and task.get('issue_id')==c['issue_id']
        and task.get('workspace_id')==e['workspace_id'] and task.get('runtime_id')==e['runtime_id']
        and task.get('wakeup_id')==assignment['wakeup_id'] and task.get('handoff_note')==
            'DELIVERY_SCOPE_AUTHOR_START '+handoff['marker']+'\nSource: '+handoff['origin']+'\n'+handoff['instruction'])
    if task.get('status') in ('pending','queued','running'):
        raise validation_job.Pending('observe original implementing task, not a replacement')
    require(task.get('status')=='completed')
    runs=[r for r in native.issue_task_runs(settings,c['issue_id']) if r.get('agent_id')==c['agent_id']]
    require(len(runs)==2 and {r['id'] for r in runs}=={c['source_task'],c['task_id']}
        and max(runs,key=lambda r:(r.get('created_at') or '',r['id']))['id']==c['task_id'])
    issue=native.issue_record(settings,c['issue_id'])
    require({k:issue.get(k) for k in ('id','workspace_id','title','description')}==context['requirements'])
    with b.db() as con:
        lease=con.execute('SELECT status,name FROM leases WHERE request_id=?',(request,)).fetchone();require(lease is not None)
        if lease[0] in ('creating','starting','running','closing'):
            raise validation_job.Pending('observe original implementation close before copying')
        require(lease[0]=='closed' and lease[1]==b.PREFIX+'-job-'+request)
        grant=con.execute('SELECT used FROM grants WHERE request_id=?',(request,)).fetchone()
        require(grant is not None and type(grant[0]) is int and grant[0]==1)
        if con.execute("SELECT 1 FROM native_bindings n JOIN leases l USING(request_id) WHERE n.scope=? "
                "AND l.status IN ('creating','starting','running','closing')",(c['scope'],)).fetchone():
            raise validation_job.Pending('source scope remains occupied')
    expected=launch.payload(b,request)  # Also validates the locked workspace and its original volume identity.
    with b.db() as con:
        creation=con.execute('SELECT payload FROM worker_creation_intents WHERE request_id=?',(request,)).fetchone()
        require(creation is not None and json.loads(creation[0])==expected)
        transport=con.execute('SELECT state FROM quality_transport_intents WHERE request_id=?',(request,)).fetchone()
        require(transport is not None and transport[0]=='opened')
        rows=con.execute('SELECT receipt_sha256,receipt FROM worker_policy_observations WHERE request_id=?',(request,)).fetchall()
        proofs=[json.loads(raw) for sha,raw in rows if hashlib.sha256(raw.encode()).hexdigest()==sha]
        proofs=[p for p in proofs if p.get('payload_sha256')==hashlib.sha256(json.dumps(expected,sort_keys=True).encode()).hexdigest()
            and p.get('worker_image')==expected['Image'] and p.get('docker_status')=='running'
            and p.get('normalized_differences')==[] and re.fullmatch('[a-f0-9]{64}',str(p.get('container_id')))]
        require(bool(proofs) and len({p['container_id'] for p in proofs})==1)
        events=con.execute('SELECT method,session_id,success FROM acp_events WHERE request_id=? ORDER BY rowid',(request,)).fetchall()
        require(all(any(r[0]==method and r[2]==1 for r in events) for method in ('initialize','session/new','session/prompt')))
        sessions={r[1] for r in events if r[0]=='session/prompt' and r[2]==1}
        require(all(con.execute('SELECT 1 FROM acp_sessions WHERE scope=? AND session_id=?',(c['scope'],session)).fetchone()
            for session in sessions))
        retired=con.execute('SELECT container_id,name,state FROM worker_retirement_intents WHERE request_id=?',(request,)).fetchone() \
            if admission.enrollment.exists(con,'worker_retirement_intents') else None
    proof=proofs[-1];actual=b.docker('GET','/containers/'+lease[1]+'/json')
    if actual is None:
        require(retired is not None and tuple(retired)==(proof['container_id'],lease[1],'gone'))
        require(b.docker('GET','/containers/'+proof['container_id']+'/json') is None)
    else:
        require(actual.get('Id')==proof['container_id'] and not worker.policy_differences(expected,actual))
        if actual.get('State',{}).get('Running') is True:
            raise validation_job.Pending('closed lease is not proof that its actual worker stopped')
        require(actual.get('State',{}).get('Status')=='exited' and actual['State'].get('Running') is False)
    return dict(task_id=c['task_id'],request_id=request,worker_inspection_sha256=quality.digest(proof),
        container_id=proof['container_id'],worker_image=expected['Image'],source_scope=c['scope'],
        prompt_sessions=sorted(sessions),native_status='completed',lease_status='closed')


def copied(b,context,result):
    task=context['admission']['task_id'];payload=grouped_create('POST','/containers/create?name=validation',context['payload'],b.PREFIX)
    key=digest(dict(task=task,kind='candidate_inventory',payload=payload))
    expected={**payload,'Labels':{**payload['Labels'],'delivery-kit.owner':b.OWNER,
        'delivery-kit.source-task':task,'delivery-kit.validation-job':key}}
    identity=dict(task=task,kind='candidate_inventory',name=b.PREFIX+'-validation-job-'+task+'-'+key[:12],payload=expected)
    with b.db() as con:
        row=con.execute('SELECT identity,state FROM validation_jobs WHERE job_key=?',(key,)).fetchone()
    require(row is not None and json.loads(row[0])==identity)
    state=json.loads(row[1])
    require(state.get('stage')=='complete' and state.get('result')==result and state.get('container_id')==result.get('container_id')
        and re.fullmatch('[a-f0-9]{64}',str(result.get('container_id'))) and result.get('approval') is False
        and type(result.get('exit_code')) is int and result['exit_code']==0
        and result.get('validation_job_key')==key and result.get('validation_contract_sha256')==digest(identity)
        and isinstance(result.get('output'),str) and len(result['output'].encode())<=65536
        and result.get('output_sha256')==hashlib.sha256(result['output'].encode()).hexdigest())
    report=json.loads(result['output']);freeze=context['freeze'];plan=freeze['plan'];facts=report['file_inventory']
    require(set(report)=={'operation','plan_sha256','base_sha','base_manifest_sha256','reviewed_manifest_sha256',
            'manifest_sha256','file_inventory','tests','execution_authorized','delivery_approval'}
        and report['operation']=='post_implementation_snapshot_v2' and report['plan_sha256']==quality.digest(plan)
        and report['base_sha']==plan['base_sha'] and report['base_manifest_sha256']==context['base']['manifest_sha256']
        and report['reviewed_manifest_sha256']==freeze['manifest_sha256'] and report['tests']==freeze['frozen_tests']
        and report['execution_authorized'] is False and report['delivery_approval'] is False
        and isinstance(facts,dict) and set(facts)==set(context['reviewed_inventory']))
    for path,item in facts.items():
        require(isinstance(item,dict) and set(item)=={'bytes','sha256'} and type(item['bytes']) is int
            and 0<=item['bytes']<=2*1024*1024 and re.fullmatch('[a-f0-9]{64}',str(item['sha256'])))
        if path not in plan['product_files']:require(item==context['reviewed_inventory'][path])
    require(all(facts[path]['sha256']==sha for path,sha in freeze['frozen_tests'].items())
        and report['manifest_sha256']==hashlib.sha256(json.dumps(dict(files=facts),sort_keys=True,separators=(',',':')).encode()).hexdigest())
    return dict(report=report,validation_job_key=key,validation_contract_sha256=digest(identity),
        container_id=result['container_id'],output_sha256=result['output_sha256'])


def observe(b,request):
    admission.enrollment.canonical(request)
    with red.observation_lock(b,request):
        previous=load(b,request)
        if previous and previous[1]['stage'] in ('awaiting_git_binding','technical_blocked'):return previous[1]
        context,state=previous or register(b,request)
        phase='delivery_observation_deadline'
        try:
            admission.enabled(b)
            with b.db() as con:
                if maintenance.current(con):raise validation_job.Pending('maintenance preserves original delivery capture')
                deadline=clock.deadline(con,b.PREFIX,state['deadline'],time.time(),budget=1800)
            require(time.time()<deadline)
            state=save(b,request,context,state,{**state,'observations':state['observations']+1,
                'alert_due':time.time()>=deadline-1200,'alert_owner':context['techlead']})
            phase='delivery_source_provenance'
            proof=completed_source(b,context)
            phase='delivery_volume_identity'
            if state['stage']=='awaiting_author_completion':
                require(b.docker('GET','/volumes/'+context['name']) is None)
                state=save(b,request,context,state,{**state,'stage':'volume_create_intent','source_provenance':proof})
                try:b.docker('POST','/volumes/create',dict(Name=context['name'],Driver='local',Labels=context['labels']))
                except TimeoutError:raise validation_job.Pending('observe original delivery volume; never repeat creation') from None
            require(state['source_provenance']==proof)
            volume=b.docker('GET','/volumes/'+context['name'])
            if volume is None:raise validation_job.Pending('observe original delivery volume creation')
            observed=admission.snapshot.volume_identity(volume,dict(name=context['name'],labels=context['labels']))
            if state['stage']=='volume_create_intent':
                state=save(b,request,context,state,{**state,'stage':'copy_pending','volume_identity':observed})
            require(state['stage']=='copy_pending' and state['volume_identity']==observed)
            phase='delivery_fixed_copy_receipt'
            with b.db() as con:
                if maintenance.current(con):raise validation_job.Pending('maintenance preserves original delivery job')
            result=validation_job.run(b,context['admission']['task_id'],'candidate_inventory',context['payload'])
            copy=copied(b,context,result)
            # The job may have completed after a control-plane restart. Bind
            # its result only after re-observing the original source and volume;
            # a completed container is not proof that a reused name is original.
            require(completed_source(b,context)==state['source_provenance']
                and admission.snapshot.volume_identity(b.docker('GET','/volumes/'+context['name']),
                    dict(name=context['name'],labels=context['labels']))==state['volume_identity'])
            return save(b,request,context,state,{**state,'stage':'awaiting_git_binding','owner':context['techlead'],
                'snapshot_volume':context['name'],'manifest_sha256':copy['report']['manifest_sha256'],'copy':copy,
                'next_action':'controller bind the exact immutable delivery to a local Git commit before Green'})
        except validation_job.Pending as pending:
            pending.progress=state;raise
        except (TimeoutError,OSError):
            pending=validation_job.Pending('observe original native/Docker/job handle; no replay')
            pending.progress=state;raise pending from None
        except (ValueError,KeyError,TypeError) as error:
            return save(b,request,context,state,{**state,'stage':'technical_blocked','owner':context['techlead'],
                'incident':dict(category=phase,error_type=type(error).__name__,automatic_retry=False,
                    next_action='Tech Lead inspect preserved source/copy identities; escalate technical diagnosis to CTO')})
