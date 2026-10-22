"""Fair opt-in native v2 handoffs through immutable delivery capture.

Does not manufacture approval or finish a release. Git/Green and revision/CTO
recovery adapters remain explicit downstream requirements. A technical block is
visible with its owner; it is never success or permission for an identical retry.
"""
import hashlib
import json
import re
import time
try:
    from . import quality_progress as progress,quality_author_admission as author
    from . import quality_test_review as review,quality_review_attestation as attestation
    from . import quality_implementation_admission as implementation,quality_delivery_capture as delivery
    from . import quality_candidate_binding as candidate,quality_green_capture as green
    from . import controller_maintenance as maintenance,maintenance_job_clock as clock,validation_job
except ImportError:
    import quality_progress as progress,quality_author_admission as author
    import quality_test_review as review,quality_review_attestation as attestation
    import quality_implementation_admission as implementation,quality_delivery_capture as delivery
    import quality_candidate_binding as candidate,quality_green_capture as green
    import controller_maintenance as maintenance,maintenance_job_clock as clock,validation_job

quality=author.quality
require=author.require
IMAGES=('QUALITY_PREP_IMAGE','QUALITY_WORKER_IMAGE','QUALITY_COPY_IMAGE','QUALITY_RED_IMAGE',
    'QUALITY_REVIEW_WORKER_IMAGE','QUALITY_GREEN_JOB_IMAGE')
TERMINAL={'technical_blocked','awaiting_sensitivity'}
STAGES=TERMINAL|{'awaiting_git_binding','waiting_author','waiting_red','review_ready','waiting_review_capacity','waiting_review_dispatch',
    'awaiting_review_admission','waiting_test_review','tests_frozen','waiting_implementation_capacity',
    'waiting_implementation_dispatch','awaiting_implementation_admission','waiting_delivery_capture','waiting_green'}


def initialize(con):
    con.execute('CREATE TABLE IF NOT EXISTS quality_team_progress(source_task TEXT PRIMARY KEY,'
        'identity TEXT,state TEXT,identity_sha256 TEXT,state_sha256 TEXT,observed_at REAL)')
    con.execute('CREATE TABLE IF NOT EXISTS quality_team_quarantine(source_task TEXT PRIMARY KEY,state TEXT,state_sha256 TEXT)')
    con.execute('CREATE TABLE IF NOT EXISTS quality_team_health(namespace TEXT PRIMARY KEY,state TEXT,state_sha256 TEXT)')


def finish(b,value):
    state={**value,'namespace':b.PREFIX,'last_tick_at':time.time()}
    with b.LOCK,b.db() as con:
        initialize(con)
        con.execute('INSERT INTO quality_team_health VALUES(?,?,?) ON CONFLICT(namespace) DO UPDATE SET '
            'state=excluded.state,state_sha256=excluded.state_sha256',
            (b.PREFIX,json.dumps(state,sort_keys=True),quality.digest(state)))
    return value


def status(b):
    with b.db() as con:
        tables={r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        required={'quality_team_health','quality_team_progress','quality_team_quarantine'}
        if not required<=tables:
            return dict(health=dict(stage='unobserved' if not required&tables else 'schema_incomplete',
                delivery_approval=False),tasks=[],quarantine=[],delivery_approval=False)
        row=con.execute('SELECT state,state_sha256 FROM quality_team_health WHERE namespace=?',(b.PREFIX,)).fetchone()
        tasks=list(con.execute('SELECT source_task,identity,state,identity_sha256,state_sha256 FROM quality_team_progress'))
        quarantine_rows=con.execute('SELECT source_task,state,state_sha256 FROM quality_team_quarantine').fetchall()
    health=json.loads(row[0]) if row else dict(stage='unobserved',delivery_approval=False)
    if row:require(quality.digest(health)==row[1] and health['namespace']==b.PREFIX)
    states=[];quarantined=[]
    for source,*saved in tasks:
        try:states.append(decode(b,source,saved)[1])
        except (ValueError,KeyError,TypeError):
            states.append(dict(source_task=source,stage='integrity_rejected',owner=b.QUALITY_CTO,delivery_approval=False))
    for source,raw,sha in quarantine_rows:
        state=json.loads(raw)
        require(quality.digest(state)==sha and state['source_task']==source)
        quarantined.append(state)
    return dict(health=health,tasks=states,quarantine=quarantined,delivery_approval=False)


def load(b,source):
    with b.db() as con:
        initialize(con)
        row=con.execute('SELECT identity,state,identity_sha256,state_sha256 FROM quality_team_progress '
            'WHERE source_task=?',(source,)).fetchone()
    if not row:return None
    return decode(b,source,row)


def decode(b,source,row):
    identity,state=json.loads(row[0]),json.loads(row[1])
    require(quality.digest(identity)==row[2] and quality.digest(state)==row[3]
        and identity['namespace']==b.PREFIX and identity['source_task']==source and state['stage'] in STAGES
        and all(state.get(k) is False for k in ('execution_authorized','green_approved','delivery_approval')))
    return identity,state


def quarantine(b,source,category):
    state=dict(stage='technical_blocked',owner=b.QUALITY_CTO,category=category,source_task=source,
        automatic_retry=False,next_action='CTO audit preserved corrupt authority; do not overwrite its evidence',
        execution_authorized=False,green_approved=False,delivery_approval=False)
    with b.LOCK,b.db() as con:
        maintenance.transaction(con);require(not maintenance.current(con))
        con.execute('INSERT OR IGNORE INTO quality_team_quarantine VALUES(?,?,?)',
            (source,json.dumps(state,sort_keys=True),quality.digest(state)))
    return state


def candidates(b):
    with b.db() as con:
        initialize(con)
        if not author.enrollment.exists(con,'quality_author_admissions'):return []
        rows=con.execute('SELECT task_id FROM quality_author_admissions').fetchall()
        skipped={row[0] for row in con.execute('SELECT source_task FROM quality_team_quarantine')}
        cursors={row[0]:row[1] for row in con.execute('SELECT source_task,observed_at FROM quality_team_progress')}
    result=[]
    for row in rows:
        source=row[0]
        if source in skipped:continue
        try:
            author.enrollment.canonical(source)
            old=load(b,source)
            if old and old[1]['stage'] in TERMINAL:continue
            result.append((cursors.get(source,0),source))
        except (ValueError,KeyError,TypeError):quarantine(b,source,'team_journal_integrity_rejected')
    return [source for _,source in sorted(result)]


def register(b,source):
    with b.db() as con:
        row=con.execute('SELECT request_id FROM quality_author_admissions WHERE task_id=?',(source,)).fetchone()
        require(row is not None);c=author.load(con,row[0]);require(c is not None)
        e=author.enrollment.lookup(con,c['issue_id'])
    require(e is not None and e['namespace']==b.PREFIX and c['namespace']==b.PREFIX
        and c['task_id']==source and c['agent_id']==e['author'] and c['run_id']==e['run_id'])
    identity=dict(namespace=b.PREFIX,source_task=source,request_id=c['request_id'],issue_id=c['issue_id'],run_id=c['run_id'],
        author=e['author'],reviewer=e['reviewer'],techlead=b.QUALITY_TECHLEAD,cto=b.QUALITY_CTO,
        author_context_sha256=quality.digest(c),enrollment_sha256=quality.digest(e))
    state=outcome('waiting_author',identity['author'])
    now=time.time();state.update(phase_started_at=now,phase_deadline=now+1800,alert_due=False)
    with b.LOCK,b.db() as con:
        maintenance.transaction(con);require(not maintenance.current(con))
        require(author.load(con,c['request_id'])==c and author.enrollment.lookup(con,c['issue_id'])==e)
        con.execute('INSERT INTO quality_team_progress VALUES(?,?,?,?,?,?)',
            (source,json.dumps(identity,sort_keys=True),json.dumps(state,sort_keys=True),quality.digest(identity),quality.digest(state),now))
    return identity,state


def outcome(stage,owner,evidence=None):
    value=dict(stage=stage,owner=owner,execution_authorized=False,green_approved=False,delivery_approval=False)
    if evidence is not None:value['evidence_sha256']=quality.digest(evidence)
    return value


def blocked(identity,evidence,*,review_problem=False,category='quality_phase_blocked'):
    value=outcome('technical_blocked',identity['cto'] if review_problem else identity['techlead'],evidence)
    value['incident']=dict(category=category,automatic_retry=False,
        next_action='technical owner diagnose preserved evidence and use a scoped changed-condition recovery; never waive gates')
    return value


def capacity(b,agent):
    with b.db() as con:
        if con.execute('SELECT 1 FROM grants g LEFT JOIN leases l USING(request_id) '
                'WHERE g.used=1 AND l.request_id IS NULL').fetchone():return False
        active=con.execute("SELECT count(*) FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone()[0]
        reserved=con.execute('SELECT count(*) FROM grants WHERE used=0 AND deadline>?',(time.time(),)).fetchone()[0]
        busy=con.execute("SELECT 1 FROM native_bindings n JOIN leases l USING(request_id) WHERE n.agent_id=? "
            "AND l.status IN ('creating','starting','running','closing')",(agent,)).fetchone()
        pending=con.execute('SELECT 1 FROM native_bindings n JOIN grants g USING(request_id) '
            'WHERE n.agent_id=? AND g.used=0 AND g.deadline>?',(agent,time.time())).fetchone()
    return active+reserved<2 and not busy and not pending


def advance(b,identity,phase):
    source=identity['source_task']
    with b.db() as con:
        c=author.load(con,identity['request_id']);e=author.enrollment.lookup(con,identity['issue_id'])
        require(c is not None and quality.digest(c)==identity['author_context_sha256']
            and e is not None and quality.digest(e)==identity['enrollment_sha256'])
        lease=con.execute('SELECT status FROM leases WHERE request_id=?',(identity['request_id'],)).fetchone()
    phase['value']='author'
    p=progress.load(b,source)
    if not p or p[1]['stage']!='review_ready':
        if p and p[1]['stage']=='technical_blocked':return blocked(identity,p[1])
        if lease is None or lease[0] in ('creating','starting','running','closing'):
            return outcome('waiting_author',identity['author'])
        if lease[0]!='closed':return blocked(identity,dict(status=lease[0]),category='author_lease_not_completed')
        result=progress.advance(b,source)
        if result['stage']=='technical_blocked':return blocked(identity,result)
        if result['stage']=='review_ready':require(progress.load(b,source)[1]==result)
        return outcome('review_ready' if result['stage']=='review_ready' else 'waiting_red',identity['reviewer'] if
            result['stage']=='review_ready' else identity['author'],result)
    phase['value']='review'
    assignment=review.load(b,source)
    if not assignment or assignment[1]['stage'] in ('prepared','dispatch_intent'):
        if (not assignment or assignment[1]['stage']=='prepared') and not capacity(b,identity['reviewer']):
            return outcome('waiting_review_capacity',identity['reviewer'])
        phase['value']='review_dispatch'
        result=review.dispatch(b,source);require(review.load(b,source)[1]==result)
        if result['stage']=='technical_blocked':return blocked(identity,result,review_problem=True)
        require(result['stage']=='awaiting_review')
        return outcome('awaiting_review_admission',identity['reviewer'],result)
    state=assignment[1]
    if state['stage']=='technical_blocked':return blocked(identity,state,review_problem=True)
    if state['stage']=='awaiting_review':return outcome('awaiting_review_admission',identity['reviewer'],state)
    require(state['stage']=='admitted')
    frozen=attestation.load(b,source)
    if frozen is None:
        phase['value']='test_review'
        frozen=attestation.observe(b,source);require(attestation.load(b,source)==frozen)
        if frozen['stage']=='tests_frozen':return outcome('tests_frozen',identity['author'],frozen)
    if frozen['stage']=='changes_requested':
        return blocked(identity,frozen,category='test_revision_adapter_required')
    if frozen['stage']=='technical_blocked':return blocked(identity,frozen,review_problem=True)
    require(frozen['stage']=='tests_frozen' and frozen['tests_approved'] is True)
    phase['value']='implementation_dispatch'
    implementing=implementation.handoff(b,source)
    if not implementing or implementing[1]['stage'] in ('prepared','dispatch_intent'):
        if (not implementing or implementing[1]['stage']=='prepared') and not capacity(b,identity['author']):
            return outcome('waiting_implementation_capacity',identity['author'])
        result=implementation.dispatch(b,source);require(implementation.handoff(b,source)[1]==result)
        if result['stage']=='technical_blocked':return blocked(identity,result)
        require(result['stage']=='awaiting_implementation')
        return outcome('awaiting_implementation_admission',identity['author'],result)
    state=implementing[1]
    if state['stage']=='technical_blocked':return blocked(identity,state)
    if state['stage']=='awaiting_implementation':return outcome('awaiting_implementation_admission',identity['author'],state)
    require(state['stage']=='admitted')
    phase['value']='delivery_capture'
    captured=delivery.load(b,state['request_id'])
    result=captured[1] if captured and captured[1]['stage'] in ('awaiting_git_binding','technical_blocked') else delivery.observe(b,state['request_id'])
    require(delivery.load(b,state['request_id'])[1]==result)
    if result['stage']=='technical_blocked':return blocked(identity,result)
    require(result['stage']=='awaiting_git_binding' and result['green_approved'] is False)
    if candidate.load(b,state['request_id']) is None:
        return outcome('awaiting_git_binding',identity['techlead'],result)
    phase['value']='green'
    result=green.observe(b,state['request_id']);require(green.load(b,state['request_id'])[1]==result)
    if result['stage']=='technical_blocked':return blocked(identity,result,category='green_observation_blocked')
    require(result['stage']=='awaiting_sensitivity')
    return outcome('awaiting_sensitivity',identity['techlead'],result)


def save(b,source,identity,before,result):
    now=time.time();after={**result,'source_task':source,'issue_id':identity['issue_id'],'run_id':identity['run_id']}
    if after['stage']==before['stage']:
        after.update(phase_started_at=before['phase_started_at'],phase_deadline=before['phase_deadline'])
    else:after.update(phase_started_at=now,phase_deadline=now+1800)
    with b.LOCK,b.db() as con:
        maintenance.transaction(con);require(not maintenance.current(con))
        deadline=clock.deadline(con,b.PREFIX,after['phase_deadline'],now,budget=1800)
        after['alert_due']=now>=deadline-1200
        changed=con.execute('UPDATE quality_team_progress SET state=?,state_sha256=?,observed_at=? '
            'WHERE source_task=? AND identity_sha256=? AND state_sha256=?',
            (json.dumps(after,sort_keys=True),quality.digest(after),now,source,quality.digest(identity),quality.digest(before)))
        require(changed.rowcount==1)
    return after


def tick(b,*,limit=2):
    require(type(limit) is int and 1<=limit<=2)
    if getattr(b,'QUALITY_TEAM_ENABLED',False) is not True:
        return dict(stage='disabled',observed=[],delivery_approval=False)
    with progress.exclusive(b):
        with b.db() as con:
            initialize(con)
            paused=maintenance.current(con)
        if paused:return finish(b,dict(stage='maintenance',observed=[],delivery_approval=False))
        missing=[k for k in ('QUALITY_V2_ENABLED','QUALITY_REVIEW_ENABLED','QUALITY_IMPLEMENTATION_ENABLED') if getattr(b,k,False) is not True]
        missing += [k for k in IMAGES if not isinstance(getattr(b,k,None),str) or not re.fullmatch('sha256:[a-f0-9]{64}',getattr(b,k))]
        for k in ('QUALITY_CTO','QUALITY_TECHLEAD'):
            try:author.enrollment.canonical(getattr(b,k,None))
            except (ValueError,TypeError):missing.append(k)
        if missing:return finish(b,dict(stage='configuration_blocked',owner=getattr(b,'QUALITY_CTO',None) or 'cto',missing=missing,observed=[],delivery_approval=False))
        observed=[]
        for source in candidates(b)[:limit]:
            try:identity,before=load(b,source) or register(b,source)
            except (ValueError,KeyError,TypeError):
                observed.append(quarantine(b,source,'source_authority_rejected'));continue
            phase=dict(value='author')
            with b.db() as con:deadline=clock.deadline(con,b.PREFIX,before['phase_deadline'],time.time(),budget=1800)
            # Re-observe authoritative phase records before declaring an old
            # view stalled. A proved admission/completion can have arrived while
            # this coordinator was offline; elapsed time alone is not its state.
            try:result=advance(b,identity,phase)
            except validation_job.Pending as pending:
                stage={'review_dispatch':'waiting_review_dispatch','test_review':'waiting_test_review',
                    'implementation_dispatch':'waiting_implementation_dispatch','delivery_capture':'waiting_delivery_capture',
                    'green':'waiting_green'}.get(phase['value'],'waiting_red')
                owner=identity['techlead'] if phase['value']=='green' else identity['reviewer'] if 'review' in phase['value'] else identity['author']
                result=outcome(stage,owner,getattr(pending,'progress',None))
            except (TimeoutError,OSError):
                result=outcome(before['stage'],before['owner'])
            except (ValueError,KeyError,TypeError):
                result=blocked(identity,dict(phase=phase['value']),review_problem='review' in phase['value'],
                    category='immutable_quality_team_evidence_rejected')
            if result['stage']==before['stage'] and result['stage'] not in TERMINAL and time.time()>=deadline:
                result=blocked(identity,before,review_problem='review' in before['stage'],category='quality_phase_observation_deadline')
            observed.append(save(b,source,identity,before,result))
        return finish(b,dict(stage='observed',observed=observed,delivery_approval=False))
