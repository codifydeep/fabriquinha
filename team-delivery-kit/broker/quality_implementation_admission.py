"""First product-only v2 admission from a controller-attested test freeze.

No legacy approval conversion or retry. Frozen baseline/new tests are inputs,
never editables. This module does not launch work or assert Green/delivery.
"""
import hashlib
import json
import re
import secrets
import time
import uuid
from execution_context import freeze,validate as validate_capsule
try:
    from . import quality_review_attestation as attestation,quality_test_review as review
    from . import quality_lifecycle_enrollment as enrollment,quality_lifecycle_v2 as quality
    from . import quality_red_snapshot as snapshot,controller_maintenance as maintenance
    from . import maintenance_job_clock as clock,native,validation_job
except ImportError:
    import quality_review_attestation as attestation,quality_test_review as review
    import quality_lifecycle_enrollment as enrollment,quality_lifecycle_v2 as quality
    import quality_red_snapshot as snapshot,controller_maintenance as maintenance
    import maintenance_job_clock as clock,native,validation_job


def require(value):
    if not value:raise ValueError('exact native frozen-test implementation admission required')


def enabled(b):
    require(getattr(b,'QUALITY_V2_ENABLED',False) is True
        and getattr(b,'QUALITY_IMPLEMENTATION_ENABLED',False) is True)


def initialize(con):
    con.execute('CREATE TABLE IF NOT EXISTS quality_implementation_handoffs('
        'source_task TEXT PRIMARY KEY,context TEXT,state TEXT,context_sha256 TEXT,state_sha256 TEXT)')
    con.execute('CREATE TABLE IF NOT EXISTS quality_implementation_admissions('
        'source_task TEXT PRIMARY KEY,task_id TEXT UNIQUE,request_id TEXT UNIQUE,context TEXT,context_sha256 TEXT)')


def handoff(b,source):
    with b.db() as con:
        initialize(con)
        row=con.execute('SELECT context,state,context_sha256,state_sha256 FROM quality_implementation_handoffs '
            'WHERE source_task=?',(source,)).fetchone()
    if not row:return None
    context,state=json.loads(row[0]),json.loads(row[1])
    require(quality.digest(context)==row[2] and quality.digest(state)==row[3]
        and context['source_task']==source and context['namespace']==b.PREFIX)
    return context,state


def frozen(b,source):
    value=attestation.load(b,source)
    require(value is not None and value['stage']=='tests_frozen' and value['tests_approved'] is True)
    plan=quality.validate(value['plan']);quality.red(plan,value['red']);quality.review(plan,value['red'],value['test_review'])
    require(value['frozen_tests']==value['red']['tests'] and value['criterion_tests']==plan['criterion_tests']
        and value['owner']==plan['author'] and value['manifest_sha256']==value['red']['manifest_sha256'])
    with b.db() as con:
        e=enrollment.lookup(con,plan['issue_id']);require(e is not None and e['namespace']==b.PREFIX
            and e['plan_sha256']==quality.digest(plan))
    return value,e


def snapshot_identity(b,source,manifest):
    with b.db() as con:
        row=con.execute('SELECT identity,state,identity_sha256,state_sha256 FROM quality_snapshot_intents '
            'WHERE task_id=?',(source,)).fetchone()
    require(row is not None)
    identity,state=json.loads(row[0]),json.loads(row[1])
    require(quality.digest(identity)==row[2] and quality.digest(state)==row[3]
        and identity['source']['task_id']==source and state['stage']=='snapshot_copied'
        and state['manifest_sha256']==manifest and state['snapshot_volume']==identity['name'])
    actual=snapshot.volume_identity(b.docker('GET','/volumes/'+identity['name']),identity)
    require(actual==state['volume_identity'])
    return dict(volume=identity['name'],identity=actual)


def register(b,source):
    enabled(b);enrollment.canonical(source)
    with review.capture.observation_lock(b,source):
        previous=handoff(b,source)
        if previous:return previous
        receipt,e=frozen(b,source)
        parent,_=review.load(b,source)
        require(parent['packet']['plan']==receipt['plan'] and parent['packet']['red']==receipt['red'])
        base=b.issue_base(e['issue_id'])
        require(all(base.get(k)==e[v] for k,v in (('issue_id','issue_id'),('base_sha','base_sha'),
            ('volume','base_volume'),('manifest_sha256','base_manifest_sha256'))))
        snap=snapshot_identity(b,source,receipt['manifest_sha256'])
        instruction=('IMPLEMENTATION V2. The exact baseline and NEW tests have been independently reviewed and frozen. '
            'Read them and the original requirements. Write only declared product files. Never edit, delete, '
            'rename, skip or weaken any test or configuration. No terminal, patches, Python execution, delegation '
            'or administrative operations. Do not recreate Red or claim Green. Stop after actual file writes; '
            'the controller captures and runs the complete frozen suite. Frozen tests: '+receipt['manifest_sha256'])
        context=dict(namespace=b.PREFIX,source_task=source,issue_id=e['issue_id'],run_id=e['run_id'],
            author=e['author'],reviewer=e['reviewer'],techlead=parent['techlead'],cto=parent['cto'],
            enrollment_sha256=quality.digest(e),frozen_sha256=quality.digest(receipt),plan=receipt['plan'],
            frozen_tests=receipt['frozen_tests'],snapshot=snap,base=base,
            origin=receipt['review_task'],instruction=instruction,requirements=parent['requirements'],
            capsule=freeze(parent['capsule']['description'],instruction))
        context['marker']=quality.digest(context)
        state=dict(stage='prepared',owner=e['author'],execution_authorized=False,delivery_approval=False)
        with b.LOCK,b.db() as con:
            maintenance.transaction(con);require(not maintenance.current(con) and enrollment.lookup(con,e['issue_id'])==e)
            con.execute('INSERT INTO quality_implementation_handoffs VALUES(?,?,?,?,?)',
                (source,json.dumps(context,sort_keys=True),json.dumps(state,sort_keys=True),quality.digest(context),quality.digest(state)))
        return context,state


def save(b,source,context,before,after):
    with b.LOCK,b.db() as con:
        maintenance.transaction(con);require(not maintenance.current(con))
        changed=con.execute('UPDATE quality_implementation_handoffs SET state=?,state_sha256=? '
            'WHERE source_task=? AND context_sha256=? AND state_sha256=?',
            (json.dumps(after,sort_keys=True),quality.digest(after),source,quality.digest(context),quality.digest(before)))
        require(changed.rowcount==1)
    return after


def dispatch(b,source):
    context,_=register(b,source)
    with review.capture.observation_lock(b,source):
        context,state=handoff(b,source)
        if state['stage'] in ('awaiting_implementation','admitted','technical_blocked'):return state
        receipt,_=frozen(b,source)
        require(quality.digest(receipt)==context['frozen_sha256'])
        settings=json.loads((b.STATE/'native.json').read_text())
        with b.db() as con:
            e=enrollment.lookup(con,context['issue_id']);require(e is not None and not maintenance.current(con))
        require(settings['workspace_id']==e['workspace_id'] and settings['runtime_id']==e['runtime_id']
            and settings['agents'].get(context['author'])=='implementation')
        allow=state['stage']=='prepared';require(state['stage'] in ('prepared','dispatch_intent'))
        if allow:
            require(b.issue_base(context['issue_id'])==context['base']
                and snapshot_identity(b,source,receipt['manifest_sha256'])==context['snapshot'])
            now=time.time()
            with b.db() as con:
                unknown=con.execute('SELECT 1 FROM grants g LEFT JOIN leases l USING(request_id) '
                    'WHERE g.used=1 AND l.request_id IS NULL').fetchone()
                active=con.execute("SELECT count(*) FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone()[0]
                reserved=con.execute('SELECT count(*) FROM grants WHERE used=0 AND deadline>?',(now,)).fetchone()[0]
                busy=con.execute("SELECT 1 FROM native_bindings n JOIN leases l USING(request_id) "
                    "WHERE n.agent_id=? AND l.status IN ('creating','starting','running','closing')",(context['author'],)).fetchone()
                pending=con.execute('SELECT 1 FROM native_bindings n JOIN grants g USING(request_id) '
                    'WHERE n.agent_id=? AND g.used=0 AND g.deadline>?',(context['author'],now)).fetchone()
                since=state.get('capacity_since',now)
                deadline=clock.deadline(con,b.PREFIX,since+1800,now,budget=1800)
            if unknown or active+reserved>=2 or busy or pending:
                updated={**state,'capacity_since':since,'capacity_alert':now>=deadline-1200,
                    'capacity_reason':'unobserved_consumed_capability' if unknown else 'occupied_workers'}
                if now>=deadline:
                    updated.update(stage='technical_blocked',owner=context['techlead'],
                        incident=dict(category='implementation_capacity_starvation',automatic_retry=False))
                state=save(b,source,context,state,updated)
                if state['stage']=='technical_blocked':return state
                raise validation_job.Pending('implementation queued for capacity; no native wakeup issued')
        if allow:state=save(b,source,context,state,{**state,'stage':'dispatch_intent','deadline':time.time()+600})
        with b.db() as con:deadline=clock.deadline(con,b.PREFIX,state['deadline'],time.time())
        try:
            row=native.ensure_scope_author_start(settings,context['issue_id'],context['author'],context['origin'],
                context['marker'],context['instruction'],allow_create=allow)
            if row is not None:
                enrollment.canonical(row['id'])
                require(row.get('agent_id')==context['author'] and row.get('issue_id')==context['issue_id'])
        except (TimeoutError,OSError):row=None
        except (ValueError,KeyError,TypeError):
            return save(b,source,context,state,{**state,'stage':'technical_blocked','owner':context['techlead'],
                'incident':dict(category='implementation_wakeup_rejected',automatic_retry=False)})
        if row is None:
            if time.time()>=deadline:
                return save(b,source,context,state,{**state,'stage':'technical_blocked','owner':context['techlead'],
                    'incident':dict(category='implementation_wakeup_unobserved',automatic_retry=False)})
            raise validation_job.Pending('observe original implementation wakeup; never repeat POST')
        return save(b,source,context,state,{**state,'stage':'awaiting_implementation','wakeup_id':row['id']})


def load(con,request):
    initialize(con)
    row=con.execute('SELECT context,context_sha256 FROM quality_implementation_admissions WHERE request_id=?',(request,)).fetchone()
    if not row:return None
    context=json.loads(row[0]);require(quality.digest(context)==row[1]);validate_capsule(context['capsule'])
    require(context['request_id']==request and context['phase']=='implementation_v2' and context['mode']=='implementation')
    phase=con.execute('SELECT n.task_id,n.agent_id,n.scope,n.issue_id,g.mode,g.attempt,q.run_id,q.phase,q.plan_sha256 '
        'FROM native_bindings n JOIN grants g USING(request_id) JOIN quality_native_scopes q '
        'ON q.request_id=n.request_id AND q.task_id=n.task_id WHERE n.request_id=?',(request,)).fetchall()
    require(len(phase)==1 and tuple(phase[0])==tuple(context[k] for k in
        ('task_id','agent_id','scope','issue_id','mode','attempt','run_id','phase','plan_sha256'))
        and con.execute('SELECT max(attempt) FROM grants WHERE task_id=?',(context['task_id'],)).fetchone()[0]==1)
    row=con.execute('SELECT receipt,receipt_sha256 FROM quality_review_attestations WHERE source_task=?',(context['source_task'],)).fetchone()
    require(row is not None and quality.digest(json.loads(row[0]))==row[1]==context['frozen_sha256'])
    receipt=json.loads(row[0]);require(receipt['stage']=='tests_frozen' and receipt['tests_approved'] is True)
    registered=con.execute('SELECT context_sha256,state,state_sha256 FROM quality_implementation_handoffs '
        'WHERE source_task=?',(context['source_task'],)).fetchone()
    require(registered is not None and registered[0]==context['handoff_sha256'])
    state=json.loads(registered[1])
    require(quality.digest(state)==registered[2] and state['stage']=='admitted'
        and state['request_id']==request and state['task_id']==context['task_id'])
    return context


def admit(b,source,task_id,agent_id,*,now=None):
    enabled(b)
    for value in (source,task_id,agent_id):enrollment.canonical(value)
    context,state=handoff(b,source);receipt,e=frozen(b,source)
    require(state['stage']=='awaiting_implementation' and quality.digest(receipt)==context['frozen_sha256']
        and agent_id==e['author'] and task_id not in (source,receipt['review_task']))
    snapshot_identity(b,source,receipt['manifest_sha256'])
    base=b.issue_base(e['issue_id'])
    require(base==context['base'])
    settings=json.loads((b.STATE/'native.json').read_text())
    task=native.task_record(settings,task_id,agent_id)
    note='DELIVERY_SCOPE_AUTHOR_START '+context['marker']+'\nSource: '+context['origin']+'\n'+context['instruction']
    require(settings['agents'].get(agent_id)=='implementation' and task.get('id')==task_id
        and task.get('agent_id')==agent_id and task.get('issue_id')==e['issue_id'] and task.get('status')=='running'
        and settings['workspace_id']==e['workspace_id'] and settings['runtime_id']==e['runtime_id']
        and task.get('workspace_id')==e['workspace_id'] and task.get('runtime_id')==e['runtime_id']
        and task.get('wakeup_id')==state['wakeup_id'] and task.get('handoff_note')==note)
    runs=[r for r in native.issue_task_runs(settings,e['issue_id']) if r.get('agent_id')==agent_id]
    require({r.get('id') for r in runs}=={source,task_id} and len(runs)==2
        and max(runs,key=lambda r:(r.get('created_at') or '',r['id']))['id']==task_id)
    issue=native.issue_record(settings,e['issue_id'])
    require({k:issue.get(k) for k in ('id','workspace_id','title','description')}==context['requirements'])
    now=time.time() if now is None else now
    with b.LOCK,b.db() as con:
        maintenance.require_admission(con)
        require(enrollment.lookup(con,e['issue_id'])==e and json.loads((b.STATE/'native.json').read_text())==settings)
        registered_base=con.execute('SELECT issue_id,base_sha,volume,manifest_sha256 FROM issue_bases WHERE issue_id=?',
            (e['issue_id'],)).fetchone()
        require(registered_base is not None and tuple(registered_base)==tuple(base[key] for key in
            ('issue_id','base_sha','volume','manifest_sha256')))
        current=con.execute('SELECT context_sha256,state_sha256 FROM quality_implementation_handoffs WHERE source_task=?',(source,)).fetchone()
        require(tuple(current)==(quality.digest(context),quality.digest(state)))
        frozen_row=con.execute('SELECT receipt,receipt_sha256 FROM quality_review_attestations WHERE source_task=?',(source,)).fetchone()
        require(frozen_row is not None and quality.digest(json.loads(frozen_row[0]))==frozen_row[1]==context['frozen_sha256'])
        require(not con.execute('SELECT 1 FROM quality_implementation_admissions WHERE source_task=? OR task_id=?',(source,task_id)).fetchone()
            and not con.execute('SELECT 1 FROM native_bindings WHERE task_id=?',(task_id,)).fetchone()
            and not con.execute('SELECT 1 FROM grants WHERE task_id=?',(task_id,)).fetchone())
        require(not con.execute('SELECT 1 FROM grants g LEFT JOIN leases l USING(request_id) WHERE g.used=1 AND l.request_id IS NULL').fetchone())
        active=con.execute("SELECT count(*) FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone()[0]
        reserved=con.execute('SELECT count(*) FROM grants WHERE used=0 AND deadline>?',(now,)).fetchone()[0]
        require(active+reserved<2 and not con.execute("SELECT 1 FROM native_bindings n JOIN leases l USING(request_id) "
            "WHERE n.agent_id=? AND l.status IN ('creating','starting','running','closing')",(agent_id,)).fetchone()
            and not con.execute('SELECT 1 FROM native_bindings n JOIN grants g USING(request_id) WHERE n.agent_id=? AND g.used=0 AND g.deadline>?',(agent_id,now)).fetchone())
        request=str(uuid.uuid4());token=secrets.token_hex(32)
        admitted=dict(namespace=b.PREFIX,source_task=source,task_id=task_id,agent_id=agent_id,issue_id=e['issue_id'],
            scope=e['workspace_id']+':'+agent_id+':implementation:'+task_id,request_id=request,mode='implementation',attempt=1,
            phase='implementation_v2',run_id=e['run_id'],plan_sha256=e['plan_sha256'],frozen_sha256=context['frozen_sha256'],
            handoff_sha256=quality.digest(context),capsule=context['capsule'])
        con.execute('INSERT INTO grants(digest,task_id,attempt,mode,request_id,deadline,used) VALUES(?,?,?,?,?,?,?)',
            (hashlib.sha256(token.encode()).hexdigest(),task_id,1,'implementation',request,now+480,0))
        con.execute('INSERT INTO native_bindings VALUES(?,?,?,?,?)',(request,task_id,agent_id,admitted['scope'],e['issue_id']))
        con.execute('INSERT INTO quality_native_scopes VALUES(?,?,?,?,?)',(request,task_id,e['run_id'],'implementation_v2',e['plan_sha256']))
        con.execute('INSERT INTO quality_implementation_admissions VALUES(?,?,?,?,?)',
            (source,task_id,request,json.dumps(admitted,sort_keys=True),quality.digest(admitted)))
        updated={**state,'stage':'admitted','task_id':task_id,'request_id':request}
        con.execute('UPDATE quality_implementation_handoffs SET state=?,state_sha256=? WHERE source_task=?',
            (json.dumps(updated,sort_keys=True),quality.digest(updated),source))
    return dict(capability=token,request_id=request,task_id=task_id,attempt=1,mode='implementation')


def selection(b,request):
    enabled(b)
    with b.db() as con:c=load(con,request);require(c is not None and c['namespace']==b.PREFIX)
    context,state=handoff(b,c['source_task']);receipt,e=frozen(b,c['source_task'])
    require(quality.digest(context)==c['handoff_sha256'] and state['stage']=='admitted' and state['request_id']==request
        and state['task_id']==c['task_id'] and quality.digest(receipt)==c['frozen_sha256'])
    snap=snapshot_identity(b,c['source_task'],receipt['manifest_sha256'])
    require(snap==context['snapshot'])
    require(b.issue_base(e['issue_id'])==context['base'])
    with b.db() as con:
        _,spec=enrollment.request(json.loads(con.execute('SELECT config FROM quality_lifecycle_enrollments WHERE issue_id=?',(e['issue_id'],)).fetchone()[0]))
    plan=context['plan']
    return dict(phase='implementation_v2',scope=c['scope'],base=context['base'],
        editable_paths=['/workspace/'+p for p in sorted(plan['product_files'])],
        read_paths=['/workspace/'+p for p in sorted(spec['files'])],
        frozen_seed=dict(volume=snap['volume'],manifest_sha256=receipt['manifest_sha256'],
            test_sha256={p:receipt['frozen_tests'][p] for p in plan['new_tests']}),
        frozen_tests=receipt['frozen_tests'],test_commands=[],terminal_allowed=False,delivery_approval=False)


def tool_config(b,request):
    selected=selection(b,request)
    return dict(version=2,phase='implementation_v2',request_id=request,
        editable_paths=selected['editable_paths'],read_paths=selected['read_paths'])
