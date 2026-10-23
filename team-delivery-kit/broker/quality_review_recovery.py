"""One changed-adapter recovery of a review that failed before any admission.

Preserves author, frozen Red/snapshot, old native task and exact assignment.
Never retries an admitted review, edits tests, approves evidence or clears a
different incident. A new one-shot marker is recorded atomically with the
specific handoff transition; the old failed run remains visible and verified.
"""
import hashlib
import json
from pathlib import Path
import time
import uuid
try:
    from . import quality_test_review as review,native,controller_maintenance as maintenance
except ImportError:
    import quality_test_review as review,native,controller_maintenance as maintenance

quality=review.quality;require=review.require
PREVIOUS_ADAPTER_SHA='2c3cc0a4561bf17fbf333ccdbcadbbee6be20d90c38f5047f35a42e53512019a'
TASK_FIELDS=('id','agent_id','issue_id','workspace_id','runtime_id','status','wakeup_id','handoff_note','scope_note_envelope_sha256')


def initialize(con):
    con.execute('CREATE TABLE IF NOT EXISTS quality_review_pre_admission_recoveries('
        'source_task TEXT PRIMARY KEY,receipt TEXT,sha256 TEXT)')


def load(b,source):
    with b.db() as con:
        if not review.capture.enrollment.exists(con,'quality_review_pre_admission_recoveries'):return None
        row=con.execute('SELECT receipt,sha256 FROM quality_review_pre_admission_recoveries WHERE source_task=?',(source,)).fetchone()
    if not row:return None
    value=json.loads(row[0]);require(quality.digest(value)==row[1] and value['source_task']==source
        and value['namespace']==b.PREFIX and value['operation']=='review_pre_admission_recovery_v2'
        and value['tests_approved'] is False and value['delivery_approval'] is False)
    return value


def marker(b,context,state):
    value=load(b,context['source_task'])
    if value is None:
        require('recovery_marker' not in state);return context['marker']
    require(value['context_sha256']==quality.digest(context) and value['new_marker']==state.get('recovery_marker')
        and value['manifest_sha256']==context['packet']['manifest_sha256']
        and value['plan_sha256']==context['packet']['plan_sha256'])
    return value['new_marker']


def failed_identity(task):return {k:task.get(k) for k in TASK_FIELDS}


def runs(b,context,state,items):
    value=load(b,context['source_task'])
    if value is None:return items
    marker(b,context,state)
    settings=json.loads((b.STATE/'native.json').read_bytes())
    old=native.task_record(settings,value['failed_task'],context['reviewer'])
    require(old['status']=='failed' and failed_identity(old)==value['failed_identity'])
    old_runs=[r for r in items if r.get('id')==value['failed_task']]
    require(len(old_runs)==1 and old_runs[0].get('status')=='failed'
        and old_runs[0].get('wakeup_id')==old['wakeup_id'])
    return [r for r in items if r.get('id')!=value['failed_task']]


def activation_ready(b,issue,maintenance_operation):
    """Reenable a held handoff, never re-admit its original author."""
    with b.db() as con:
        require(review.capture.enrollment.exists(con,'quality_review_pre_admission_recoveries'))
        rows=con.execute('SELECT source_task FROM quality_review_pre_admission_recoveries').fetchall()
    records=[load(b,row[0]) for row in rows]
    records=[r for r in records if r['issue_id']==issue];require(len(records)==1)
    value=records[0];context,state=review.load(b,value['source_task'])
    require(state['stage']=='prepared' and value['request']['maintenance_operation']==maintenance_operation)
    marker(b,context,state)
    review.capture.authorize_source(b,value['source_task'])
    settings=json.loads((b.STATE/'native.json').read_bytes());observed=native.issue_task_runs(settings,issue)
    require({r['id'] for r in observed}=={value['source_task'],value['failed_task']})
    require([r['status'] for r in observed if r['id']==value['source_task']]==['completed'])
    require(runs(b,context,state,[r for r in observed if r.get('agent_id')==context['reviewer']])==[])
    return value


def register(b,source,failed_task,adapter_sha,maintenance_operation):
    for value in (source,failed_task,maintenance_operation):review.capture.enrollment.canonical(value)
    require(isinstance(adapter_sha,str) and len(adapter_sha)==64)
    request=dict(source_task=source,failed_task=failed_task,adapter_sha256=adapter_sha,maintenance_operation=maintenance_operation)
    prior=load(b,source)
    if prior is not None:
        require(prior['request']==request);return prior
    require(getattr(native,'REVIEW_NOTE_ENVELOPE_VERSION',None)==1
        and hashlib.sha256(Path(native.__file__).read_bytes()).hexdigest()==adapter_sha
        and adapter_sha!=PREVIOUS_ADAPTER_SHA)
    with review.capture.observation_lock(b,source):
        context,before=review.load(b,source)
        require(before['stage']=='awaiting_review' and 'recovery_marker' not in before)
        old_note='DELIVERY_REVIEW_START '+context['marker']+'\nSource: '+source+'\n'+context['instruction']
        settings=json.loads((b.STATE/'native.json').read_bytes())
        old=native.task_record(settings,failed_task,context['reviewer'])
        require(old.get('status')=='failed' and old.get('id')==failed_task
            and old.get('agent_id')==context['reviewer'] and old.get('issue_id')==context['packet']['issue_id']
            and old.get('wakeup_id')==before['wakeup_id'] and old.get('handoff_note')==old_note
            and old.get('scope_note_envelope_verified') is True
            and old.get('workspace_id')==settings['workspace_id'] and old.get('runtime_id')==settings['runtime_id'])
        previous_runs=[r for r in native.issue_task_runs(settings,old['issue_id']) if r.get('agent_id')==context['reviewer']]
        require(len(previous_runs)==1 and previous_runs[0].get('id')==failed_task)
        require(not native.task_messages(settings,failed_task))
        with b.db() as con:
            red=con.execute('SELECT state FROM quality_red_captures WHERE task_id=?',(source,)).fetchone()
        require(red is not None and review.progress.packet(b,source,json.loads(red[0]))==context['packet'])
        require(not maintenance.native_active(b))
        # This same transaction preserves the former handoff/team states and
        # replaces only their active pointers. No author or Red row is changed.
        with b.LOCK,b.db() as con:
            maintenance.transaction(con);initialize(con)
            paused=maintenance.current(con)
            require(paused and paused['stage']=='sealed' and paused['drained'] is True
                and paused['namespace']==b.PREFIX and paused['operation_id']==maintenance_operation)
            require(not con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing') LIMIT 1").fetchone())
            require(not con.execute('SELECT 1 FROM grants g LEFT JOIN leases l USING(request_id) WHERE g.deadline>? '
                'AND (g.used=0 OR (g.used=1 AND l.request_id IS NULL)) LIMIT 1',(time.time(),)).fetchone())
            require(json.loads((b.STATE/'native.json').read_bytes())==settings)
            require(not con.execute('SELECT 1 FROM quality_review_admissions WHERE source_task=? OR task_id=?',(source,failed_task)).fetchone())
            require(not con.execute('SELECT 1 FROM native_bindings WHERE task_id=?',(failed_task,)).fetchone()
                and not con.execute('SELECT 1 FROM grants WHERE task_id=?',(failed_task,)).fetchone())
            saved=con.execute('SELECT context_sha256,state_sha256 FROM quality_test_reviews WHERE source_task=?',(source,)).fetchone()
            require(saved is not None and tuple(saved)==(quality.digest(context),quality.digest(before)))
            row=con.execute('SELECT identity,state,identity_sha256,state_sha256 FROM quality_team_progress WHERE source_task=?',(source,)).fetchone()
            require(row is not None)
            team_identity,team_before=json.loads(row[0]),json.loads(row[1])
            require(quality.digest(team_identity)==row[2] and quality.digest(team_before)==row[3]
                and team_identity['source_task']==source and team_identity['issue_id']==old['issue_id']
                and team_before['stage'] in ('awaiting_review_admission','waiting_test_review','technical_blocked'))
            if team_before['stage']=='technical_blocked':
                require(team_before.get('incident',{}).get('category') in ('review_pre_admission_native_failed','quality_phase_observation_deadline'))
            new_marker=quality.digest(dict(operation='review_pre_admission_recovery_v2',request=request,context_sha256=quality.digest(context)))
            receipt=dict(operation='review_pre_admission_recovery_v2',namespace=b.PREFIX,source_task=source,issue_id=old['issue_id'],
                failed_task=failed_task,request=request,failed_identity=failed_identity(old),
                previous_adapter_sha256=PREVIOUS_ADAPTER_SHA,adapter_sha256=adapter_sha,
                context_sha256=quality.digest(context),manifest_sha256=context['packet']['manifest_sha256'],
                plan_sha256=context['packet']['plan_sha256'],red_sha256=context['packet']['red_sha256'],
                previous_review_state=before,previous_team_state=team_before,new_marker=new_marker,
                tests_approved=False,delivery_approval=False,model_calls=0)
            con.execute('INSERT INTO quality_review_pre_admission_recoveries VALUES(?,?,?)',(source,json.dumps(receipt,sort_keys=True),quality.digest(receipt)))
            after={**before,'stage':'prepared','recovery_marker':new_marker}
            after.pop('wakeup_id',None);after.pop('deadline',None)
            changed=con.execute('UPDATE quality_test_reviews SET state=?,state_sha256=? WHERE source_task=? AND context_sha256=? AND state_sha256=?',
                (json.dumps(after,sort_keys=True),quality.digest(after),source,quality.digest(context),quality.digest(before)))
            require(changed.rowcount==1)
            now=time.time();team_after=dict(stage='review_ready',owner=context['reviewer'],execution_authorized=False,green_approved=False,
                source_task=source,issue_id=old['issue_id'],run_id=context['packet']['run_id'],
                delivery_approval=False,phase_started_at=now,phase_deadline=now+1800,alert_due=False,recovery_marker=new_marker)
            changed=con.execute('UPDATE quality_team_progress SET state=?,state_sha256=?,observed_at=? WHERE source_task=? AND state_sha256=?',
                (json.dumps(team_after,sort_keys=True),quality.digest(team_after),now,source,row[3]))
            require(changed.rowcount==1)
        return receipt
