"""One changed-guard review recovery after admission, strictly before ACP.

Old capability, admission, failed task, attestation and snapshot stay immutable.
Only a new read-only reviewer task may be admitted, with versioned records.
No model/tool execution, test edit, author replay or approval occurs here.
"""
import hashlib
import json
from pathlib import Path
import re
import stat
import time
try:
    from . import quality_test_review as review,quality_review_attestation as attestation
    from . import controller_maintenance as maintenance,native,worker_creation_intent as intents
except ImportError:
    import quality_test_review as review,quality_review_attestation as attestation
    import controller_maintenance as maintenance,native,worker_creation_intent as intents

quality=review.quality;require=review.require
OLD_GUARD_SHA='08596fa65cd468386fe4bf0dc57c54727c7b065c931bff365f25544692626ab9'
OLD_CONTROLLER_IMAGE='sha256:c2db074cfb9af791a31062d7979a1766e02a31f1c738c94c01d67760e29e5320'
FIELDS=('id','agent_id','issue_id','workspace_id','runtime_id','status','wakeup_id','handoff_note')


def initialize(con):
    con.execute('CREATE TABLE IF NOT EXISTS quality_review_bootstrap_recoveries(source_task TEXT PRIMARY KEY,receipt TEXT,sha256 TEXT)')
    con.execute('CREATE TABLE IF NOT EXISTS quality_review_attempts(source_task TEXT PRIMARY KEY,task_id TEXT UNIQUE,request_id TEXT UNIQUE,context TEXT,context_sha256 TEXT)')


def load(b,source):
    with b.db() as con:
        if not review.capture.enrollment.exists(con,'quality_review_bootstrap_recoveries'):return None
        row=con.execute('SELECT receipt,sha256 FROM quality_review_bootstrap_recoveries WHERE source_task=?',(source,)).fetchone()
    if not row:return None
    value=json.loads(row[0]);require(quality.digest(value)==row[1] and value['source_task']==source
        and value['namespace']==b.PREFIX and value['operation']=='review_zero_acp_bootstrap_recovery_v2'
        and value['tests_approved'] is False and value['delivery_approval'] is False and value['model_calls']==0)
    return value


def eligible(b,source):
    value=load(b,source)
    if value is None:return False
    _,state=review.load(b,source)
    return state['stage'] in ('prepared','dispatch_intent','awaiting_review') and state.get('bootstrap_marker')==value['new_marker']


def marker(b,context,state):
    value=load(b,context['source_task'])
    if value is None:
        require('bootstrap_marker' not in state);return None
    require(value['context_sha256']==quality.digest(context) and value['new_marker']==state.get('bootstrap_marker'))
    return value['new_marker']


def exclude_failed(b,context,state,items):
    value=load(b,context['source_task'])
    if value is None:return items
    marker(b,context,state)
    settings=json.loads((b.STATE/'native.json').read_bytes())
    task=native.task_record(settings,value['failed_task'],context['reviewer'])
    require({k:task.get(k) for k in FIELDS}==value['failed_identity'] and task['status']=='failed')
    old=[r for r in items if r.get('id')==value['failed_task']]
    require(len(old)==1 and old[0].get('status')=='failed' and old[0].get('wakeup_id')==task.get('wakeup_id'))
    return [r for r in items if r.get('id')!=value['failed_task']]


def admission_table(b,con,source,context,state,task):
    value=load(b,source)
    if value is None:return 'quality_review_admissions'
    marker(b,context,state)
    row=con.execute('SELECT task_id,request_id,context_sha256 FROM quality_review_admissions WHERE source_task=?',(source,)).fetchone()
    require(row is not None and tuple(row)==(value['failed_task'],value['old_request'],value['old_admission_sha256'])
        and task!=value['failed_task']
        and not con.execute('SELECT 1 FROM quality_review_attempts WHERE source_task=? OR task_id=?',(source,task)).fetchone())
    return 'quality_review_attempts'


def archived_worker(b,cid,request):
    root=b.STATE/'helper-archives'/cid;require(root.resolve()==root and not root.is_symlink())
    def read(name):
        path=root/name;info=path.stat()
        require(path.resolve()==path and not path.is_symlink() and stat.S_ISREG(info.st_mode)
            and info.st_nlink==1 and not info.st_mode&0o077 and info.st_size<=1048576)
        return path.read_bytes()
    metadata_raw=read('metadata.json');logs=read('logs.txt');metadata=json.loads(metadata_raw)
    require(metadata['container_id']==cid and metadata['owner']==b.OWNER
        and metadata['name']==b.PREFIX+'-job-'+request and metadata['identity_key']=='delivery-kit.request'
        and metadata['identity_value']==request and metadata['logs_sha256']==hashlib.sha256(logs).hexdigest())
    return dict(container_id=cid,metadata_sha256=hashlib.sha256(metadata_raw).hexdigest(),logs_sha256=metadata['logs_sha256'])


def register(b,source,failed_task,guard_sha,operation,*,installation):
    for value in (source,failed_task,operation):review.capture.enrollment.canonical(value)
    require(re.fullmatch('[a-f0-9]{64}',guard_sha) and guard_sha!=OLD_GUARD_SHA
        and callable(getattr(intents,'qualified_fact',None))
        and hashlib.sha256(Path(intents.__file__).read_bytes()).hexdigest()==guard_sha)
    require(isinstance(installation,dict) and set(installation)=={'install_operation','previous_image','current_image','previous_container','current_container'}
        and installation['previous_image']==OLD_CONTROLLER_IMAGE and installation['current_image']!=OLD_CONTROLLER_IMAGE
        and re.fullmatch('sha256:[a-f0-9]{64}',str(installation['current_image']))
        and all(re.fullmatch('[a-f0-9]{64}',str(installation[k])) for k in ('previous_container','current_container'))
        and installation['previous_container']!=installation['current_container'])
    review.capture.enrollment.canonical(installation['install_operation'])
    request=dict(source_task=source,failed_task=failed_task,guard_sha256=guard_sha,maintenance_operation=operation,installation=installation)
    previous=load(b,source)
    if previous:require(previous['request']==request);return previous
    controller=b.docker('GET','/containers/'+b.PREFIX+'-execution-broker-1/json')
    require(controller is not None and controller['Id']==installation['current_container']
        and controller['Image']==installation['current_image'] and controller['State']['Running'] is True
        and controller['Config']['Labels'].get('com.docker.compose.project')==b.PREFIX
        and controller['Config']['Labels'].get('com.docker.compose.service')=='execution-broker')
    with review.capture.observation_lock(b,source):
        context,state=review.load(b,source)
        require(state['stage']=='admitted' and state['review_task']==failed_task and 'bootstrap_marker' not in state)
        old_request=state['request_id'];settings=json.loads((b.STATE/'native.json').read_bytes())
        task=native.task_record(settings,failed_task,context['reviewer'])
        require(task.get('status')=='failed' and task.get('id')==failed_task and task.get('agent_id')==context['reviewer']
            and task.get('issue_id')==context['packet']['issue_id'] and task.get('wakeup_id')==state['wakeup_id']
            and task.get('handoff_note')==review.note(b,context,state)
            and task.get('workspace_id')==settings['workspace_id'] and task.get('runtime_id')==settings['runtime_id'])
        require(not native.task_messages(settings,failed_task) and not maintenance.native_active(b))
        c,registered,assignment=attestation.launch.context_for(b,old_request)
        require(registered==context and assignment==state)
        old_attestation=attestation.load(b,source)
        require(old_attestation and old_attestation['stage']=='technical_blocked'
            and old_attestation['request_id']==old_request and old_attestation['tests_approved'] is False
            and old_attestation.get('incident',{}).get('category')=='native_identity')
        expected=attestation.launch.evidence_payload(b,old_request);payload_sha=hashlib.sha256(json.dumps(expected,sort_keys=True).encode()).hexdigest()
        with b.db() as con:
            proofs=[json.loads(raw) for sha,raw in con.execute('SELECT receipt_sha256,receipt FROM worker_policy_observations WHERE request_id=?',(old_request,))
                if hashlib.sha256(raw.encode()).hexdigest()==sha]
        proofs=[p for p in proofs if p.get('request_id')==old_request and p.get('payload_sha256')==payload_sha
            and p.get('worker_image')==expected['Image'] and p.get('docker_status')=='running' and p.get('normalized_differences')==[]]
        require(bool(proofs) and len({p['container_id'] for p in proofs})==1)
        cid=proofs[-1]['container_id'];require(re.fullmatch('[a-f0-9]{64}',cid))
        archive=archived_worker(b,cid,old_request)
        require(b.docker('GET','/containers/'+cid+'/json') is None
            and b.docker('GET','/containers/'+b.PREFIX+'-job-'+old_request+'/json') is None)
        runs=native.issue_task_runs(settings,context['packet']['issue_id'])
        prior_runs=[{k:native_record.get(k) for k in FIELDS} for native_record in
            (native.task_record(settings,r['id'],r['agent_id']) for r in runs)]
        require(len(prior_runs)==len({r['id'] for r in prior_runs}) and
            all(r['status'] in ('completed','failed','cancelled') for r in prior_runs))
        with b.db() as con:
            known={r[0] for r in con.execute('SELECT task_id FROM native_bindings WHERE issue_id=?',(context['packet']['issue_id'],))}
            old_recoveries=con.execute('SELECT source_task FROM quality_review_pre_admission_recoveries').fetchall() if review.capture.enrollment.exists(con,'quality_review_pre_admission_recoveries') else []
        try:from . import quality_review_recovery as pre_admission
        except ImportError:import quality_review_recovery as pre_admission
        for (prior_source,) in old_recoveries:
            prior=pre_admission.load(b,prior_source)
            if prior['issue_id']!=context['packet']['issue_id']:continue
            old_context,old_state=review.load(b,prior_source)
            pre_admission.runs(b,old_context,old_state,[r for r in runs if r.get('agent_id')==old_context['reviewer']])
            known.add(prior['failed_task'])
        require({r['id'] for r in prior_runs}==known)
        with b.LOCK,b.db() as con:
            maintenance.transaction(con);initialize(con)
            held=maintenance.current(con)
            require(held and held['stage']=='sealed' and held['drained'] is True and held['operation_id']==operation)
            require(not con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone()
                and not con.execute('SELECT 1 FROM grants g LEFT JOIN leases l USING(request_id) WHERE g.deadline>? '
                    'AND (g.used=0 OR (g.used=1 AND l.request_id IS NULL))',(time.time(),)).fetchone())
            require(json.loads((b.STATE/'native.json').read_bytes())==settings)
            grant=con.execute('SELECT used,attempt FROM grants WHERE request_id=?',(old_request,)).fetchone()
            lease=con.execute('SELECT status,name FROM leases WHERE request_id=?',(old_request,)).fetchone()
            require(tuple(grant)==(1,1) and tuple(lease)==('failed',b.PREFIX+'-job-'+old_request)
                and old_request not in b.SESSIONS)
            require(not con.execute('SELECT 1 FROM acp_events WHERE request_id=?',(old_request,)).fetchone()
                and not con.execute('SELECT 1 FROM acp_sessions WHERE scope=?',(c['scope'],)).fetchone())
            if review.capture.enrollment.exists(con,'quality_transport_intents'):
                require(not con.execute('SELECT 1 FROM quality_transport_intents WHERE request_id=?',(old_request,)).fetchone())
            if review.capture.enrollment.exists(con,'observed_read_stream'):
                require(not con.execute('SELECT 1 FROM observed_read_stream WHERE task_id=? OR request_id=?',(failed_task,old_request)).fetchone())
            if review.capture.enrollment.exists(con,'tool_events'):
                require(not con.execute('SELECT 1 FROM tool_events WHERE request_id=?',(old_request,)).fetchone())
            startup=con.execute('SELECT state FROM acp_startups WHERE request_id=?',(old_request,)).fetchone()
            require(startup and json.loads(startup[0])['stage']=='failed')
            saved=con.execute('SELECT context_sha256,state_sha256 FROM quality_test_reviews WHERE source_task=?',(source,)).fetchone()
            require(tuple(saved)==(quality.digest(context),quality.digest(state)))
            preserved=con.execute('SELECT receipt_sha256 FROM quality_review_attestations WHERE source_task=? AND request_id=?',(source,old_request)).fetchone()
            require(preserved is not None and preserved[0]==quality.digest(old_attestation))
            old_admission=con.execute('SELECT context_sha256 FROM quality_review_admissions WHERE source_task=? AND task_id=? AND request_id=?',
                (source,failed_task,old_request)).fetchone();require(old_admission is not None)
            team=con.execute('SELECT state,state_sha256 FROM quality_team_progress WHERE source_task=?',(source,)).fetchone()
            require(team is not None and quality.digest(json.loads(team[0]))==team[1] and json.loads(team[0])['stage']=='technical_blocked')
            new_marker=quality.digest(dict(operation='review_zero_acp_bootstrap_recovery_v2',request=request,context_sha256=quality.digest(context)))
            receipt=dict(operation='review_zero_acp_bootstrap_recovery_v2',namespace=b.PREFIX,source_task=source,
                issue_id=context['packet']['issue_id'],failed_task=failed_task,old_request=old_request,
                old_admission_sha256=old_admission[0],failed_identity={k:task.get(k) for k in FIELDS},
                context_sha256=quality.digest(context),request=request,new_marker=new_marker,
                previous_assignment=state,previous_attestation=old_attestation,previous_team=json.loads(team[0]),
                prior_runs=sorted(prior_runs,key=lambda r:r['id']),
                worker_retirement=archive,manifest_sha256=context['packet']['manifest_sha256'],
                previous_guard_sha256=OLD_GUARD_SHA,guard_sha256=guard_sha,
                model_calls=0,tests_approved=False,delivery_approval=False)
            con.execute('INSERT INTO quality_review_bootstrap_recoveries VALUES(?,?,?)',(source,json.dumps(receipt,sort_keys=True),quality.digest(receipt)))
            after={**state,'stage':'prepared','bootstrap_marker':new_marker}
            for key in ('request_id','review_task','wakeup_id','deadline'):after.pop(key,None)
            con.execute('UPDATE quality_test_reviews SET state=?,state_sha256=? WHERE source_task=?',
                (json.dumps(after,sort_keys=True),quality.digest(after),source))
            now=time.time();team_after={k:v for k,v in json.loads(team[0]).items() if k not in ('incident','evidence_sha256')}
            team_after.update(stage='review_ready',owner=context['reviewer'],phase_started_at=now,phase_deadline=now+1800,alert_due=False)
            con.execute('UPDATE quality_team_progress SET state=?,state_sha256=?,observed_at=? WHERE source_task=?',
                (json.dumps(team_after,sort_keys=True),quality.digest(team_after),now,source))
        return receipt


def activation_ready(b,issue,operation):
    with b.db() as con:
        if not review.capture.enrollment.exists(con,'quality_review_bootstrap_recoveries'):return False
        sources=con.execute('SELECT source_task FROM quality_review_bootstrap_recoveries').fetchall()
    records=[load(b,r[0]) for r in sources];records=[r for r in records if r['issue_id']==issue]
    if not records:return False
    require(len(records)==1);record=records[0];context,state=review.load(b,record['source_task'])
    require(state['stage']=='prepared' and record['request']['maintenance_operation']==operation)
    marker(b,context,state)
    require(attestation.load(b,record['source_task'],request_id=record['old_request'])==record['previous_attestation']
        and hashlib.sha256(Path(intents.__file__).read_bytes()).hexdigest()==record['guard_sha256'])
    settings=json.loads((b.STATE/'native.json').read_bytes());runs=native.issue_task_runs(settings,issue)
    actual=[{k:value.get(k) for k in FIELDS} for value in (native.task_record(settings,r['id'],r['agent_id']) for r in runs)]
    require(sorted(actual,key=lambda r:r['id'])==record['prior_runs'])
    return True
