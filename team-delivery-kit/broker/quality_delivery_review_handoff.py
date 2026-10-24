"""Default-off native delivery-review handoff/admission, not review approval.

Reauthenticates copy/Green/sensitivity jobs, enrollment, immutable volume and
native identities. Unknown wakeup effects are observed, never resubmitted.
This adapter is not installed, routed to worker launch or called by team ticks
yet. Enabling it requires the readonly launch, validation and verdict bridge.
"""
import hashlib
import json
import math
import secrets
import time
import uuid
from execution_context import freeze,validate as validate_capsule
try:
    from . import quality_sensitivity_capture as sensitivity,quality_delivery_capture as delivery
    from . import quality_lifecycle_enrollment as enrollment,quality_review_history as history
    from . import controller_maintenance as maintenance,maintenance_job_clock as clock,native,validation_job
except ImportError:
    import quality_sensitivity_capture as sensitivity,quality_delivery_capture as delivery
    import quality_lifecycle_enrollment as enrollment,quality_review_history as history
    import controller_maintenance as maintenance,maintenance_job_clock as clock,native,validation_job

quality=delivery.quality
TABLES=('quality_delivery_captures','quality_green_captures','quality_sensitivity_captures')
STAGES={'prepared','dispatch_intent','awaiting_delivery_review_admission','admitted','technical_blocked'}


def require(value):
    if not value:raise ValueError('exact native same-snapshot delivery-review handoff required')


def enabled(b):
    require(all(getattr(b,k,False) is True for k in
        ('QUALITY_V2_ENABLED','QUALITY_REVIEW_ENABLED','QUALITY_DELIVERY_REVIEW_ENABLED')))


def initialize(con):
    con.execute('CREATE TABLE IF NOT EXISTS quality_delivery_review_handoffs('
        'implementation_request TEXT PRIMARY KEY,context TEXT,state TEXT,context_sha256 TEXT,state_sha256 TEXT)')
    con.execute('CREATE TABLE IF NOT EXISTS quality_delivery_review_admissions('
        'implementation_request TEXT PRIMARY KEY,task_id TEXT UNIQUE,request_id TEXT UNIQUE,context TEXT,context_sha256 TEXT)')


def load(b,request):
    enrollment.canonical(request)
    with b.db() as con:
        initialize(con)
        row=con.execute('SELECT context,state,context_sha256,state_sha256 FROM quality_delivery_review_handoffs '
            'WHERE implementation_request=?',(request,)).fetchone()
    if row is None:return None
    context,state=json.loads(row[0]),json.loads(row[1])
    require(quality.digest(context)==row[2] and quality.digest(state)==row[3]
        and context['namespace']==b.PREFIX and context['implementation_request']==request
        and state['stage'] in STAGES and all(state.get(k) is False for k in
            ('execution_authorized','merge_authorized','delivery_approval')))
    validate_capsule(context['capsule'])
    return context,state


def job_result(b,key):
    with b.db() as con:row=con.execute('SELECT identity,state FROM validation_jobs WHERE job_key=?',(key,)).fetchone()
    require(row is not None)
    state=json.loads(row[1]);require(state.get('stage')=='complete')
    return state['result']


def records(con,request,jobs):
    rows={}
    for table in TABLES:
        row=con.execute('SELECT context,state,context_sha256,state_sha256 FROM '+table+' WHERE request_id=?',(request,)).fetchone()
        require(row is not None and quality.digest(json.loads(row[0]))==row[2]
            and quality.digest(json.loads(row[1]))==row[3])
        rows[table]=[row[2],row[3]]
    result={}
    for key in jobs:
        row=con.execute('SELECT identity,state FROM validation_jobs WHERE job_key=?',(key,)).fetchone()
        require(row is not None);result[key]=quality.digest([json.loads(v) for v in row])
    return dict(captures=rows,jobs=result)


def provenance(b,request):
    source,state=delivery.load(b,request);require(state['stage']=='awaiting_git_binding')
    completed=delivery.completed_source(b,source)
    descriptor=delivery.export_descriptor(b,request)
    require(delivery.copied(b,source,job_result(b,state['copy']['validation_job_key']))==state['copy'])
    green,green_state=sensitivity.green.load(b,request);require(green_state['stage']=='awaiting_sensitivity')
    require(sensitivity.green.observed(b,green,job_result(b,green_state['observation']['validation_job_key']))
        ==green_state['observation'])
    context,controls=sensitivity.load(b,request)
    require(controls['stage']=='awaiting_independent_delivery_review'
        and sensitivity.provenance(b,request)=={k:v for k,v in context.items() if k!='payload'}
        and sensitivity.observed(b,context,job_result(b,controls['observation']['validation_job_key']))
            ==controls['observation'])
    evidence={**context['evidence'],'sensitivity':controls['observation']['sensitivity']}
    facts=quality.qualify_sensitivity(context['plan'],evidence)
    require(facts['manifest_sha256']==descriptor['manifest_sha256']==context['manifest_sha256']
        and evidence['green']['task_id']==completed['task_id']==source['admission']['task_id'])
    with b.db() as con:
        enrolled=enrollment.lookup(con,context['plan']['issue_id'])
        require(enrolled is not None and enrolled['namespace']==b.PREFIX and enrolled['plan_sha256']==quality.digest(context['plan'])
            and source['enrollment_sha256']==quality.digest(enrolled))
        jobs=[state['copy']['validation_job_key'],green_state['observation']['validation_job_key'],controls['observation']['validation_job_key']]
        hashes=records(con,request,jobs)
    implementing,_=delivery.admission.handoff(b,source['admission']['source_task'])
    return dict(namespace=b.PREFIX,implementation_request=request,source_task=source['admission']['source_task'],
        origin_task=completed['task_id'],issue_id=context['plan']['issue_id'],run_id=context['plan']['run_id'],
        author=context['plan']['author'],reviewer=context['plan']['reviewer'],cto=context['cto'],
        plan=context['plan'],evidence=evidence,base=context['base'],file_inventory=descriptor['file_inventory'],
        manifest_sha256=facts['manifest_sha256'],commit_sha=facts['commit_sha'],
        snapshot=dict(volume=context['candidate_volume'],identity=context['candidate_identity']),
        enrollment_sha256=quality.digest(enrolled),upstream_records=hashes,requirements=source['requirements'],
        description=implementing['capsule']['description'])


def note(context):
    return 'DELIVERY_REVIEW_START '+context['marker']+'\nSource: '+context['origin_task']+'\n'+context['instruction']


def check_records(con,context):
    require(records(con,context['implementation_request'],context['upstream_records']['jobs'])==context['upstream_records'])
    enrolled=enrollment.lookup(con,context['issue_id'])
    require(enrolled is not None and quality.digest(enrolled)==context['enrollment_sha256'])
    return enrolled


def prepare(b,request):
    enabled(b);enrollment.canonical(request)
    with delivery.red.observation_lock(b,request):
        with b.db() as con:
            if maintenance.current(con):raise validation_job.Pending('maintenance preserves delivery-review handoff')
        previous=load(b,request)
        if previous:return previous
        context=provenance(b,request);description=context.pop('description')
        instruction=('INDEPENDENT V2 DELIVERY REVIEW. Review the exact implemented snapshot, requirements, '
            'frozen tests, Green and negative-control evidence. This is not test-design approval. '
            'No writes, patches, shell, delegation or administration. Never edit tests or recreate Red. '
            'Full-suite validation must run as a fixed controller job tied to YOUR execution; '
            'the implementer Green is not your validation. No claim can replace reads or a job receipt. '
            'Find defects with exact file/criterion evidence; technical review problems go to CTO, not CEO. '
            'Approval is only for this delivery snapshot, never merge or release. '
            'Snapshot: '+context['manifest_sha256']+' Commit: '+context['commit_sha'])
        context.update(read_paths=['/delivery/'+p for p in sorted(context['file_inventory'])],
            instruction=instruction,capsule=freeze(description,instruction))
        context['marker']=quality.digest(context)
        state=dict(stage='prepared',owner=context['reviewer'],execution_authorized=False,merge_authorized=False,delivery_approval=False)
        with b.LOCK,b.db() as con:
            maintenance.transaction(con)
            if maintenance.current(con):raise validation_job.Pending('maintenance pauses delivery-review registration')
            check_records(con,context)
            con.execute('INSERT INTO quality_delivery_review_handoffs VALUES(?,?,?,?,?)',
                (request,json.dumps(context,sort_keys=True),json.dumps(state,sort_keys=True),quality.digest(context),quality.digest(state)))
        return context,state


def fresh(b,context):
    actual=provenance(b,context['implementation_request']);actual.pop('description')
    require(actual=={k:v for k,v in context.items() if k not in ('marker','instruction','capsule','read_paths')})


def save(b,request,context,before,after):
    with b.LOCK,b.db() as con:
        maintenance.transaction(con)
        if maintenance.current(con):raise validation_job.Pending('maintenance preserves delivery-review intent')
        if before['stage']=='prepared' and after['stage']=='dispatch_intent':
            if not available(con,context['reviewer'],time.time(),own=request):
                raise validation_job.Pending('another delivery-review intent reserved capacity; no wakeup issued')
        changed=con.execute('UPDATE quality_delivery_review_handoffs SET state=?,state_sha256=? '
            'WHERE implementation_request=? AND context_sha256=? AND state_sha256=?',
            (json.dumps(after,sort_keys=True),quality.digest(after),request,quality.digest(context),quality.digest(before)))
        require(changed.rowcount==1)
    return after


def available(con,agent,now,*,own=None):
    require(type(now) in (int,float) and math.isfinite(now) and now>=0)
    if con.execute('SELECT 1 FROM grants g LEFT JOIN leases l USING(request_id) WHERE g.used=1 AND l.request_id IS NULL').fetchone():return False
    active=con.execute("SELECT count(*) FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone()[0]
    reserved=con.execute('SELECT count(*) FROM grants WHERE used=0 AND deadline>?',(now,)).fetchone()[0]
    busy=con.execute("SELECT 1 FROM native_bindings n JOIN leases l USING(request_id) WHERE n.agent_id=? "
        "AND l.status IN ('creating','starting','running','closing')",(agent,)).fetchone()
    pending=con.execute('SELECT 1 FROM native_bindings n JOIN grants g USING(request_id) '
        'WHERE n.agent_id=? AND g.used=0 AND g.deadline>?',(agent,now)).fetchone()
    # A native wakeup can exist before its callback obtains a grant/lease.
    # Reserve these exact intents too, rather than racing a second source into
    # the same profile while the first is still awaiting native admission.
    intents=0
    for request,raw,state,sha,state_sha in con.execute('SELECT implementation_request,context,state,context_sha256,state_sha256 '
            'FROM quality_delivery_review_handoffs'):
        context,state=json.loads(raw),json.loads(state)
        require(quality.digest(context)==sha and quality.digest(state)==state_sha
            and context['implementation_request']==request and state['stage'] in STAGES)
        if request==own or state['stage'] not in ('dispatch_intent','awaiting_delivery_review_admission'):continue
        if context['reviewer']==agent:return False
        intents+=1
    if con.execute("SELECT 1 FROM sqlite_master WHERE name='quality_delivery_revisions'").fetchone():
        for request,raw,state,sha,state_sha in con.execute('SELECT review_request,context,state,context_sha256,state_sha256 FROM quality_delivery_revisions'):
            context,state=json.loads(raw),json.loads(state)
            require(quality.digest(context)==sha and quality.digest(state)==state_sha and context['review_request']==request
                and state['stage'] in ('prepared','dispatch_intent','awaiting_product_revision_admission','technical_blocked'))
            if request==own or state['stage'] not in ('dispatch_intent','awaiting_product_revision_admission'):continue
            if context['author']==agent:return False
            intents+=1
    return active+reserved+intents<2 and not busy and not pending


def hold(b,request,context,state,category):
    return save(b,request,context,state,{**state,'stage':'technical_blocked','owner':context['cto'],
        'incident':dict(category=category,automatic_retry=False,
            next_action='CTO diagnose preserved delivery-review evidence; never repeat a wakeup POST or waive gates')})


def dispatch(b,request):
    context,_=prepare(b,request)
    with delivery.red.observation_lock(b,request):
        context,state=load(b,request)
        if state['stage'] in ('awaiting_delivery_review_admission','admitted','technical_blocked'):return state
        fresh(b,context);settings=json.loads((b.STATE/'native.json').read_bytes())
        with b.db() as con:
            enrolled=check_records(con,context)
            if maintenance.current(con):raise validation_job.Pending('maintenance pauses delivery-review dispatch')
        require(settings['workspace_id']==enrolled['workspace_id'] and settings['runtime_id']==enrolled['runtime_id']
            and settings['agents'].get(context['reviewer'])=='review')
        allow=state['stage']=='prepared';require(state['stage'] in ('prepared','dispatch_intent'))
        if allow:
            now=time.time();since=state.get('capacity_since',now)
            with b.db() as con:
                ready=available(con,context['reviewer'],now,own=request)
                deadline=clock.deadline(con,b.PREFIX,since+1800,now,budget=1800)
            if not ready:
                state=save(b,request,context,state,{**state,'capacity_since':since,'alert_due':now>=deadline-1200})
                if now>=deadline:return hold(b,request,context,state,'delivery_review_capacity_starvation')
                raise validation_job.Pending('delivery review queued for capacity; no wakeup issued')
            state=save(b,request,context,state,{**state,'stage':'dispatch_intent','deadline':now+600})
        with b.db() as con:deadline=clock.deadline(con,b.PREFIX,state['deadline'],time.time())
        try:
            wake=native.ensure_review_start(settings,context['issue_id'],context['reviewer'],context['origin_task'],
                context['marker'],context['instruction'],allow_create=allow)
            if wake is not None:
                enrollment.canonical(wake['id'])
                require(wake.get('issue_id')==context['issue_id'] and wake.get('agent_id')==context['reviewer'])
        except (TimeoutError,OSError):wake=None
        except (ValueError,KeyError,TypeError):return hold(b,request,context,state,'delivery_review_wakeup_rejected')
        if wake is None:
            if time.time()>=deadline:return hold(b,request,context,state,'delivery_review_dispatch_unobserved')
            raise validation_job.Pending('observe original delivery-review wakeup; no repeated POST')
        return save(b,request,context,state,{**state,'stage':'awaiting_delivery_review_admission','wakeup_id':wake['id']})


def admission(con,request):
    initialize(con)
    row=con.execute('SELECT context,context_sha256 FROM quality_delivery_review_admissions WHERE request_id=?',(request,)).fetchone()
    if row is None:return None
    value=json.loads(row[0]);validate_capsule(value['capsule'])
    require(quality.digest(value)==row[1] and value['request_id']==request and value['phase']=='delivery_review_v2'
        and value['mode']=='review' and value['editable_paths']==[] and value['delivery_approval'] is False)
    row=con.execute('SELECT context,state,context_sha256,state_sha256 FROM quality_delivery_review_handoffs '
        'WHERE implementation_request=?',(value['implementation_request'],)).fetchone();require(row is not None)
    context,state=json.loads(row[0]),json.loads(row[1])
    require(quality.digest(context)==row[2]==value['handoff_sha256'] and quality.digest(state)==row[3]
        and state['stage']=='admitted' and state['task_id']==value['task_id'] and state['request_id']==request
        and all(value[k]==context[k] for k in ('namespace','source_task','issue_id','run_id','manifest_sha256','commit_sha','read_paths','capsule'))
        and value['snapshot_volume']==context['snapshot']['volume'] and value['agent_id']==context['reviewer'])
    check_records(con,context)
    rows=con.execute('SELECT n.task_id,n.agent_id,n.scope,n.issue_id,g.mode,g.attempt,q.run_id,q.phase,q.plan_sha256 '
        'FROM native_bindings n JOIN grants g USING(request_id) JOIN quality_native_scopes q '
        'ON q.request_id=n.request_id AND q.task_id=n.task_id WHERE n.request_id=?',(request,)).fetchall()
    require(len(rows)==1 and tuple(rows[0])==tuple(value[k] for k in
        ('task_id','agent_id','scope','issue_id','mode','attempt','run_id','phase','plan_sha256'))
        and con.execute('SELECT max(attempt) FROM grants WHERE task_id=?',(value['task_id'],)).fetchone()[0]==1)
    return value


def review_history(b,context,task_id,settings):
    try:from . import quality_test_revision as revision
    except ImportError:import quality_test_revision as revision
    with b.db() as con:
        old=history.rows(con,'admission',source=context['source_task']);known=set()
        for raw,sha in old:
            c=json.loads(raw);require(quality.digest(c)==sha and c['namespace']==b.PREFIX
                and c['source_task']==context['source_task'] and c['agent_id']==context['reviewer']
                and c['issue_id']==context['issue_id'] and c['phase']=='test_review_v2')
            known.add(c['task_id'])
    runs=[r for r in native.issue_task_runs(settings,context['issue_id']) if r.get('agent_id')==context['reviewer']]
    runs=revision.exclude_prior_reviews(b,context['source_task'],runs)
    require(bool(known) and len(runs)==len(known)+1 and {r.get('id') for r in runs}==known|{task_id}
        and all(r.get('status') in ('completed','failed','cancelled') for r in runs if r.get('id') in known))


def admit(b,request,task_id,agent_id,*,now=None):
    enabled(b)
    for value in (request,task_id,agent_id):enrollment.canonical(value)
    context,state=load(b,request)
    require(state['stage']=='awaiting_delivery_review_admission' and agent_id==context['reviewer']
        and agent_id!=context['author'] and task_id not in {context['evidence'][k]['task_id'] for k in ('red','test_review','green')})
    fresh(b,context);settings=json.loads((b.STATE/'native.json').read_bytes())
    with b.db() as con:enrolled=check_records(con,context)
    require(settings['workspace_id']==enrolled['workspace_id'] and settings['runtime_id']==enrolled['runtime_id']
        and settings['agents'].get(agent_id)=='review')
    task=native.task_record(settings,task_id,agent_id)
    require(task.get('id')==task_id and task.get('agent_id')==agent_id and task.get('issue_id')==context['issue_id']
        and task.get('status')=='running' and task.get('workspace_id')==enrolled['workspace_id']
        and task.get('runtime_id')==enrolled['runtime_id'] and task.get('wakeup_id')==state['wakeup_id']
        and task.get('handoff_note')==note(context))
    review_history(b,context,task_id,settings)
    issue=native.issue_record(settings,context['issue_id'])
    require({k:issue.get(k) for k in ('id','workspace_id','title','description')}==context['requirements'])
    now=time.time() if now is None else now
    with b.LOCK,b.db() as con:
        maintenance.require_admission(con);check_records(con,context)
        require(json.loads((b.STATE/'native.json').read_bytes())==settings and available(con,agent_id,now,own=request))
        recorded=con.execute('SELECT context_sha256,state_sha256 FROM quality_delivery_review_handoffs '
            'WHERE implementation_request=?',(request,)).fetchone()
        require(tuple(recorded)==(quality.digest(context),quality.digest(state))
            and not con.execute('SELECT 1 FROM native_bindings WHERE task_id=?',(task_id,)).fetchone()
            and not con.execute('SELECT 1 FROM grants WHERE task_id=?',(task_id,)).fetchone())
        execution=str(uuid.uuid4());token=secrets.token_hex(32)
        value=dict(namespace=b.PREFIX,implementation_request=request,source_task=context['source_task'],
            issue_id=context['issue_id'],run_id=context['run_id'],task_id=task_id,agent_id=agent_id,
            scope=enrolled['workspace_id']+':'+agent_id+':review:'+task_id,request_id=execution,mode='review',attempt=1,
            phase='delivery_review_v2',plan_sha256=quality.digest(context['plan']),handoff_sha256=quality.digest(context),
            snapshot_volume=context['snapshot']['volume'],manifest_sha256=context['manifest_sha256'],commit_sha=context['commit_sha'],
            read_paths=context['read_paths'],editable_paths=[],capsule=context['capsule'],delivery_approval=False)
        con.execute('INSERT INTO grants(digest,task_id,attempt,mode,request_id,deadline,used) VALUES(?,?,?,?,?,?,?)',
            (hashlib.sha256(token.encode()).hexdigest(),task_id,1,'review',execution,now+480,0))
        con.execute('INSERT INTO native_bindings VALUES(?,?,?,?,?)',(execution,task_id,agent_id,value['scope'],context['issue_id']))
        con.execute('INSERT INTO quality_native_scopes VALUES(?,?,?,?,?)',
            (execution,task_id,context['run_id'],'delivery_review_v2',quality.digest(context['plan'])))
        con.execute('INSERT INTO quality_delivery_review_admissions VALUES(?,?,?,?,?)',
            (request,task_id,execution,json.dumps(value,sort_keys=True),quality.digest(value)))
        updated={**state,'stage':'admitted','task_id':task_id,'request_id':execution}
        con.execute('UPDATE quality_delivery_review_handoffs SET state=?,state_sha256=? WHERE implementation_request=?',
            (json.dumps(updated,sort_keys=True),quality.digest(updated),request))
    return dict(capability=token,request_id=execution,task_id=task_id,attempt=1,mode='review',delivery_approval=False)


def current(b,request):
    """Revalidate the admitted native execution before any future launch/job."""
    enabled(b)
    with b.db() as con:
        c=admission(con,request);require(c is not None and c['namespace']==b.PREFIX)
    context,state=load(b,c['implementation_request']);fresh(b,context)
    settings=json.loads((b.STATE/'native.json').read_bytes())
    with b.db() as con:enrolled=check_records(con,context)
    require(settings['workspace_id']==enrolled['workspace_id'] and settings['runtime_id']==enrolled['runtime_id']
        and settings['agents'].get(c['agent_id'])=='review')
    task=native.task_record(settings,c['task_id'],c['agent_id'])
    require(task.get('id')==c['task_id'] and task.get('agent_id')==c['agent_id'] and task.get('issue_id')==c['issue_id']
        and task.get('workspace_id')==enrolled['workspace_id'] and task.get('runtime_id')==enrolled['runtime_id']
        and task.get('status')=='running' and task.get('wakeup_id')==state['wakeup_id']
        and task.get('handoff_note')==note(context))
    review_history(b,context,c['task_id'],settings)
    issue=native.issue_record(settings,c['issue_id'])
    require({k:issue.get(k) for k in ('id','workspace_id','title','description')}==context['requirements'])
    return c,context
