"""Controller-only final review attestation. Source-only, not routed/installed.

Native completion, closed execution, inspected policy and byte-bound ACP reads
are mandatory. Durable decisions never replay a review, authorize merge or
declare a release delivered. Technical incidents belong to the CTO.
"""
import hashlib
import json
import re
import time
import quality_delivery_review_verdict as verdict
from quality_review_verdict import rejection_category
try:
    from . import quality_delivery_review_launch as launch,read_stream_receipts as stream
    from . import controller_maintenance as maintenance,maintenance_job_clock as clock,validation_job
except ImportError:
    import quality_delivery_review_launch as launch,read_stream_receipts as stream
    import controller_maintenance as maintenance,maintenance_job_clock as clock,validation_job

review=launch.review
quality=review.quality
require=review.require


def initialize(con):
    con.execute('CREATE TABLE IF NOT EXISTS quality_delivery_review_attestations('
        'request_id TEXT PRIMARY KEY,identity TEXT,receipt TEXT,identity_sha256 TEXT,receipt_sha256 TEXT)')
    con.execute('CREATE TABLE IF NOT EXISTS quality_delivery_review_windows('
        'request_id TEXT PRIMARY KEY,identity_sha256 TEXT,state TEXT,state_sha256 TEXT)')


def identity(c,assignment,result):
    return dict(namespace=c['namespace'],request_id=c['request_id'],task_id=c['task_id'],
        admission_sha256=quality.digest(c),assignment_sha256=quality.digest(assignment),
        validation_state_sha256=quality.digest(result))


def load(b,request):
    with b.db() as con:
        initialize(con)
        row=con.execute('SELECT identity,receipt,identity_sha256,receipt_sha256 '
            'FROM quality_delivery_review_attestations WHERE request_id=?',(request,)).fetchone()
    if not row:return None
    bound,receipt=json.loads(row[0]),json.loads(row[1])
    c,assignment,result=launch.context_for(b,request)
    require(quality.digest(bound)==row[2] and quality.digest(receipt)==row[3]
        and bound==identity(c,assignment,result) and receipt['request_id']==request
        and receipt['stage'] in ('delivery_reviewed','changes_requested','technical_blocked')
        and all(receipt[k] is False for k in ('execution_authorized','merge_authorized','delivery_approval')))
    return receipt


def window(b,request,bound,owner):
    now=time.time()
    with b.LOCK,b.db() as con:
        maintenance.transaction(con)
        if maintenance.current(con):raise validation_job.Pending('maintenance preserves final review evidence')
        initialize(con);row=con.execute('SELECT identity_sha256,state,state_sha256 '
            'FROM quality_delivery_review_windows WHERE request_id=?',(request,)).fetchone()
        if row:
            state=json.loads(row[1]);require(row[0]==quality.digest(bound) and quality.digest(state)==row[2])
        else:state=dict(stage='awaiting_final_review_evidence',owner=owner,deadline=now+1800,observations=0)
        deadline=clock.deadline(con,b.PREFIX,state['deadline'],now,budget=1800)
        state.update(observations=state['observations']+1,alert_due=now>=deadline-1200)
        con.execute('INSERT INTO quality_delivery_review_windows VALUES(?,?,?,?) ON CONFLICT(request_id) '
            'DO UPDATE SET state=excluded.state,state_sha256=excluded.state_sha256',
            (request,quality.digest(bound),json.dumps(state,sort_keys=True),quality.digest(state)))
    return state,now>=deadline


def collect(b,c,assignment,validated,phase):
    phase['value']='delivery_review_native_identity';review.fresh(b,assignment)
    with b.db() as con:enrolled=review.check_records(con,assignment)
    settings=json.loads((b.STATE/'native.json').read_bytes())
    require(settings['workspace_id']==enrolled['workspace_id'] and settings['runtime_id']==enrolled['runtime_id']
        and settings['agents'].get(c['agent_id'])=='review')
    task=review.native.task_record(settings,c['task_id'],c['agent_id'])
    if task.get('status') in ('pending','queued','running'):raise validation_job.Pending('observe same final reviewer')
    _,state=review.load(b,c['implementation_request'])
    require(task.get('status')=='completed' and task.get('id')==c['task_id'] and task.get('agent_id')==c['agent_id']
        and task.get('issue_id')==c['issue_id'] and task.get('workspace_id')==settings['workspace_id']
        and task.get('runtime_id')==settings['runtime_id'] and task.get('wakeup_id')==state['wakeup_id']
        and task.get('handoff_note')==review.note(assignment))
    review.review_history(b,assignment,c['task_id'],settings)
    issue=review.native.issue_record(settings,c['issue_id'])
    require({k:issue.get(k) for k in ('id','workspace_id','title','description')}==assignment['requirements'])
    phase['value']='delivery_review_closed_execution';expected=launch.evidence_payload(b,c['request_id'])
    with b.db() as con:
        lease=con.execute('SELECT status,name FROM leases WHERE request_id=?',(c['request_id'],)).fetchone();require(lease is not None)
        if lease[0] in ('creating','starting','running','closing'):raise validation_job.Pending('observe same final review close')
        require(lease[0]=='closed' and lease[1]==b.PREFIX+'-job-'+c['request_id'])
        grant=con.execute('SELECT used FROM grants WHERE request_id=?',(c['request_id'],)).fetchone();require(grant is not None and grant[0]==1)
        creation=con.execute('SELECT payload FROM worker_creation_intents WHERE request_id=?',(c['request_id'],)).fetchone()
        transport=con.execute('SELECT state FROM quality_transport_intents WHERE request_id=?',(c['request_id'],)).fetchone()
        require(creation is not None and json.loads(creation[0])==expected and transport is not None and transport[0]=='opened')
        inspections=con.execute('SELECT receipt_sha256,receipt FROM worker_policy_observations WHERE request_id=?',(c['request_id'],)).fetchall()
        proofs=[json.loads(raw) for sha,raw in inspections if hashlib.sha256(raw.encode()).hexdigest()==sha]
        proofs=[p for p in proofs if p.get('payload_sha256')==hashlib.sha256(json.dumps(expected,sort_keys=True).encode()).hexdigest()
            and p.get('worker_image')==expected['Image'] and p.get('docker_status')=='running'
            and p.get('normalized_differences')==[] and re.fullmatch('[a-f0-9]{64}',str(p.get('container_id')))]
        require(bool(proofs))
        events=con.execute('SELECT method,session_id,success FROM acp_events WHERE request_id=? ORDER BY rowid',(c['request_id'],)).fetchall()
        require(any(r[0]=='initialize' and r[2]==1 for r in events) and any(r[0]=='session/new' and r[2]==1 for r in events))
        prompts=[r for r in events if r[0]=='session/prompt' and r[2]==1]
        require(bool(prompts) and all(con.execute('SELECT 1 FROM acp_sessions WHERE scope=? AND session_id=?',
            (c['scope'],r[1])).fetchone() for r in prompts))
        messages=stream.load(con,c['task_id'])
    phase['value']='delivery_review_terminal_verdict';output=(task.get('result') or {}).get('output')
    value=verdict.parse(output,assignment['plan'],assignment['evidence'],validated['validation'])
    phase['value']='delivery_review_complete_reads'
    observed=verdict.inspect_reads(value,assignment['file_inventory'],assignment['read_paths'],messages)
    action=value['action'];stage={'approve_delivery':'delivery_reviewed','request_changes':'changes_requested','escalate_cto':'technical_blocked'}[action]
    result=dict(operation='immutable_delivery_review_attestation_v2',request_id=c['request_id'],task_id=c['task_id'],
        implementation_request=c['implementation_request'],stage=stage,owner=assignment['cto'] if action=='escalate_cto' else assignment['author'],
        manifest_sha256=c['manifest_sha256'],commit_sha=c['commit_sha'],verdict=value,
        native_output_sha256=hashlib.sha256(output.encode()).hexdigest(),reads_stream_sha256=quality.digest(messages),
        reads={p:{k:v for k,v in r.items() if k!='line_content'} for p,r in observed.items()},
        worker_inspection_sha256=quality.digest(proofs[-1]),execution_authorized=False,merge_authorized=False,delivery_approval=False)
    if action=='approve_delivery':
        result['decision'],result['policy_facts']=verdict.approval(assignment['plan'],assignment['evidence'],validated['validation'],value,observed)
    return result


def observe(b,request):
    review.enrollment.canonical(request)
    with review.delivery.red.observation_lock(b,request):
        previous=load(b,request)
        if previous:return previous
        launch.enabled(b);c,assignment,validated=launch.context_for(b,request);bound=identity(c,assignment,validated)
        waiting,expired=window(b,request,bound,assignment['reviewer']);phase=dict(value='delivery_review_observation_deadline')
        try:
            require(not expired);receipt=collect(b,c,assignment,validated,phase)
        except (validation_job.Pending,TimeoutError,OSError) as error:
            if isinstance(error,validation_job.Pending):pending=error
            else:pending=validation_job.Pending('observe original final review evidence; never replay')
            pending.progress=waiting;raise pending from None
        except (ValueError,KeyError,TypeError) as error:
            receipt=dict(operation='immutable_delivery_review_attestation_v2',request_id=request,task_id=c['task_id'],
                implementation_request=c['implementation_request'],stage='technical_blocked',owner=assignment['cto'],
                incident=dict(category=phase['value'],error_type=type(error).__name__,verdict_rejection=rejection_category(error),
                    automatic_retry=False,next_action='CTO diagnose exact native execution, snapshot, reads and verdict; no gate waiver'),
                execution_authorized=False,merge_authorized=False,delivery_approval=False)
        with b.LOCK,b.db() as con:
            maintenance.transaction(con)
            if maintenance.current(con):raise validation_job.Pending('maintenance preserves final review receipt')
            require(review.admission(con,request)==c);review.check_records(con,assignment)
            if 'reads_stream_sha256' in receipt:require(quality.digest(stream.load(con,c['task_id']))==receipt['reads_stream_sha256'])
            con.execute('INSERT INTO quality_delivery_review_attestations VALUES(?,?,?,?,?)',
                (request,json.dumps(bound,sort_keys=True),json.dumps(receipt,sort_keys=True),quality.digest(bound),quality.digest(receipt)))
        return receipt
