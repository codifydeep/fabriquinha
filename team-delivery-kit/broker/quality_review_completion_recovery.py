"""Changed-condition successor of a rejected or transport-failed review.

Controller/operator only. Preserves every old admission, task, attestation and
capability; issues no capability and starts no work. Coordinator dispatches a
fresh read-only review only after maintenance release. Same condition cannot
be registered again, even under another qualification or image build tag.
"""
import hashlib
import json
from pathlib import Path
import re
import time
import quality_review_stop as stop
import quality_phase_tools as phase
import quality_review_verdict as verdict
import quality_review_paging as paging
import quality_review_budget as budget
import install_quality_review_stop as installer
from review_execution_evidence import validate as validate_execution_controls
import review_execution_evidence as execution_evidence
try:
    from . import quality_test_review as review,quality_review_attestation as attestation,quality_review_history as history
    from . import controller_maintenance as maintenance,native,read_stream_receipts
except ImportError:
    import quality_test_review as review,quality_review_attestation as attestation,quality_review_history as history
    import controller_maintenance as maintenance,native,read_stream_receipts

quality=review.quality;require=review.require
FIELDS=('id','agent_id','issue_id','workspace_id','runtime_id','status','wakeup_id','handoff_note')


def initialize(con):
    history.initialize(con)
    con.execute('CREATE TABLE IF NOT EXISTS quality_review_completion_recoveries('
        'source_task TEXT,previous_request TEXT UNIQUE,marker TEXT UNIQUE,receipt TEXT,sha256 TEXT,'
        'PRIMARY KEY(source_task,previous_request))')


def records(b,source):
    with b.db() as con:
        if not history.exists(con,'quality_review_completion_recoveries'):return []
        rows=con.execute('SELECT receipt,sha256 FROM quality_review_completion_recoveries WHERE source_task=?',(source,)).fetchall()
    result=[]
    for raw,sha in rows:
        value=json.loads(raw)
        require(quality.digest(value)==sha and value['namespace']==b.PREFIX and value['source_task']==source
            and value['operation']=='review_completion_changed_condition_v3' and value['tests_approved'] is False
            and value['delivery_approval'] is False and value['model_calls']==0 and value['incident_closed'] is False)
        result.append(value)
    result.sort(key=lambda v:v['ordinal'])
    require([v['ordinal'] for v in result]==list(range(1,len(result)+1))
        and len({v['condition_sha256'] for v in result})==len(result))
    return result


def marker(b,context,state):
    previous=records(b,context['source_task'])
    if not previous:
        require('completion_marker' not in state);return None
    current=previous[-1]
    require(current['context_sha256']==quality.digest(context) and state.get('completion_marker')==current['new_marker'])
    return current['new_marker']


def eligible(b,source):
    current=records(b,source)
    if not current:return False
    context,state=review.load(b,source);marker(b,context,state)
    return state['stage'] in ('prepared','dispatch_intent','awaiting_review')


def exclude_completed(b,context,state,runs):
    """Historical name; failed runs retain their exact failure fingerprint."""
    previous=records(b,context['source_task'])
    if not previous:return runs
    marker(b,context,state);settings=json.loads((b.STATE/'native.json').read_bytes())
    result=list(runs)
    for record in previous:
        task=native.task_record(settings,record['previous_task'],context['reviewer'])
        output=(task.get('result') or {}).get('output')
        require({k:task.get(k) for k in FIELDS}==record['previous_identity']
            and attestation.load(b,context['source_task'],request_id=record['previous_request'])==record['previous_attestation'])
        if 'transport' in record['request'] or record['request'].get('failed_review') is True:
            try:from . import quality_review_capacity_recovery as capacity
            except ImportError:import quality_review_capacity_recovery as capacity
            require(capacity.failure_sha256(task)==record['native_failure_sha256'])
        else:
            require(task['status']=='completed' and isinstance(output,str)
                and hashlib.sha256(output.encode()).hexdigest()==record['native_output_sha256'])
        matching=[r for r in result if r.get('id')==record['previous_task']]
        require(len(matching)==1 and matching[0].get('status')==task['status']
            and matching[0].get('wakeup_id')==task['wakeup_id'])
        result=[r for r in result if r.get('id')!=record['previous_task']]
    return result


def admission_table(b,con,source,context,state,task):
    previous=records(b,source)
    if not previous:return None
    marker(b,context,state)
    require(task not in {r['previous_task'] for r in previous}
        and not con.execute('SELECT 1 FROM quality_review_successor_admissions WHERE task_id=?',(task,)).fetchone())
    return 'quality_review_successor_admissions'


def qualification(b,value,operation):
    require(isinstance(value,dict) and value.get('operation')=='qualified_review_stop_worker_v1'
        and value.get('namespace')==b.PREFIX and value.get('maintenance_operation')==operation
        and value.get('container_retired') is True and value.get('model_calls')==0
        and value.get('tests_approved') is False and value.get('delivery_approval') is False
        and value.get('worker_image')==getattr(b,'QUALITY_REVIEW_WORKER_IMAGE',None)
        and value.get('worker_image')==getattr(b,'QUALITY_WORKER_IMAGE',None))
    review.capture.enrollment.canonical(value['qualification_id'])
    image=b.docker('GET','/images/'+value['worker_image']+'/json') or {}
    require(image.get('Id')==value['worker_image'] and image.get('Config',{}).get('User')=='10000:10000'
        and not image.get('Config',{}).get('Volumes')
        and image.get('Config',{}).get('Labels',{}).get('delivery-kit.component')=='quality-author-worker')
    modules={'feedback':stop,'phase':phase,'verdict':verdict,'installer':installer,'paging':paging,'budget':budget}
    guards={key:hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest() for key,module in modules.items()}
    guards['handler']=hashlib.sha256(Path(__file__).with_name('review_tool_policy.py').read_bytes()).hexdigest()
    require(value.get('guards')==guards)
    report=value.get('report') or {}
    require(report.get('operation')=='real_hermes_review_stop_loop_canary_v1' and report.get('status')=='passed'
        and report.get('provider')=='fixed_loopback_not_model' and report.get('acp') is True
        and report.get('model_calls')==0 and report.get('fixed_provider_calls')==3
        and report.get('feedback_rounds')==1 and report.get('max_iterations')==40
        and report.get('same_agent') is True and report.get('protected_files_unchanged') is True
        and report.get('tests_approved') is False and report.get('delivery_approval') is False
        and isinstance(report.get('guard_sources'),dict)
        and set(report['guard_sources'])==set(guards)|{'loop','acp','session','executor'}
        and all(report['guard_sources'][key]==sha for key,sha in guards.items())
        and all(re.fullmatch('[a-f0-9]{64}',str(v)) for v in report['guard_sources'].values()))
    validate_execution_controls(report.get('execution_controls'))
    execution_evidence.validate_scale(report.get('scale_controls'))
    require(type(report.get('total_fixed_provider_calls')) is int
        and report['total_fixed_provider_calls']==13+report['scale_controls']['summary_provider_calls']
        and report.get('fixture_source_sha256')==hashlib.sha256(Path(execution_evidence.__file__).read_bytes()).hexdigest())
    return quality.digest(report['guard_sources'])


def register(b,source,previous_task,operation,*,qualified,installation,transport=None,failed_review=False):
    require(type(failed_review) is bool and not (failed_review and transport is not None))
    native_failed=failed_review or transport is not None
    for value in (source,previous_task,operation):review.capture.enrollment.canonical(value)
    condition=qualification(b,qualified,operation)
    capacity_request=None
    if transport is not None:
        try:from . import quality_review_capacity_recovery as capacity
        except ImportError:import quality_review_capacity_recovery as capacity
        require(isinstance(transport,dict) and isinstance(transport.get('rejection'),dict))
        capacity_request=transport['rejection'].get('execution_id');review.capture.enrollment.canonical(capacity_request)
        condition=quality.digest(dict(worker=condition,transport=capacity.validate(b,transport,operation,capacity_request)))
    require(isinstance(installation,dict) and set(installation)=={'install_operation','previous_image','current_image','previous_container','current_container'}
        and installation['previous_image']!=installation['current_image']
        and all(re.fullmatch('sha256:[a-f0-9]{64}',str(installation[k])) for k in ('previous_image','current_image'))
        and all(re.fullmatch('[a-f0-9]{64}',str(installation[k])) for k in ('previous_container','current_container'))
        and installation['previous_container']!=installation['current_container'])
    review.capture.enrollment.canonical(installation['install_operation'])
    request=dict(source_task=source,previous_task=previous_task,maintenance_operation=operation,
        qualification=qualified,installation=installation)
    if transport is not None:request['transport']=transport
    if failed_review:request['failed_review']=True
    previous=records(b,source)
    same=[r for r in previous if r['previous_task']==previous_task]
    if same:
        require(len(same)==1 and same[0]['request']==request);return same[0]
    require(condition not in {r['condition_sha256'] for r in previous})
    controller=b.docker('GET','/containers/'+b.PREFIX+'-execution-broker-1/json')
    require(controller and controller['Id']==installation['current_container'] and controller['Image']==installation['current_image']
        and controller['State']['Running'] is True and controller['Config']['Labels'].get('com.docker.compose.project')==b.PREFIX
        and controller['Config']['Labels'].get('com.docker.compose.service')=='execution-broker')
    with review.capture.observation_lock(b,source):
        context,state=review.load(b,source)
        require(state['stage']=='admitted' and state['review_task']==previous_task)
        previous_request=state['request_id'];settings=json.loads((b.STATE/'native.json').read_bytes())
        task=native.task_record(settings,previous_task,context['reviewer'])
        require(task.get('id')==previous_task and task.get('agent_id')==context['reviewer']
            and task.get('status')==('failed' if native_failed else 'completed')
            and task.get('issue_id')==context['packet']['issue_id'] and task.get('wakeup_id')==state['wakeup_id']
            and task.get('handoff_note')==review.note(b,context,state)
            and task.get('workspace_id')==settings['workspace_id'] and task.get('runtime_id')==settings['runtime_id'])
        runs=review.eligible_runs(b,context,state,[r for r in native.issue_task_runs(settings,task['issue_id']) if r.get('agent_id')==context['reviewer']])
        require(len(runs)==1 and runs[0].get('id')==previous_task and not maintenance.native_active(b))
        old=attestation.load(b,source)
        require(old and old['stage']=='technical_blocked' and old['request_id']==previous_request and old['tests_approved'] is False
            and old.get('incident',{}).get('category') in
                (('native_identity',) if native_failed else ('native_terminal_verdict','complete_snapshot_reads')))
        admission,registered,assignment=attestation.launch.context_for(b,previous_request)
        require(registered==context and assignment==state)
        output=(task.get('result') or {}).get('output')
        if not native_failed:require(isinstance(output,str))
        else:
            if transport is not None:require(previous_request==capacity_request)
            else:
                try:from . import quality_review_capacity_recovery as capacity
                except ImportError:import quality_review_capacity_recovery as capacity
            failure_sha=capacity.failure_sha256(task)
        with b.db() as con:
            capture=json.loads(con.execute('SELECT context FROM quality_red_captures WHERE task_id=?',(source,)).fetchone()[0])
            messages=read_stream_receipts.load(con,previous_task)
            payload=json.loads(con.execute('SELECT payload FROM worker_creation_intents WHERE request_id=?',(previous_request,)).fetchone()[0])
            proofs=[json.loads(raw) for sha,raw in con.execute('SELECT receipt_sha256,receipt FROM worker_policy_observations WHERE request_id=?',(previous_request,))
                if hashlib.sha256(raw.encode()).hexdigest()==sha]
            retirement=con.execute('SELECT container_id,name,state FROM worker_retirement_intents WHERE request_id=?',(previous_request,)).fetchone()
            if native_failed:
                events=con.execute('SELECT method,success FROM acp_events WHERE request_id=?',(previous_request,)).fetchall()
                require(all(any(r[0]==method and r[1]==success for r in events)
                    for method,success in (('initialize',1),('session/new',1),('session/prompt',0))))
                if failed_review:
                    require(all(len([r for r in events if r[0]==method])==1
                        for method in ('initialize','session/new','session/prompt')))
        if not native_failed:
            diagnostic=attestation.completion_diagnostic(output,context['packet'],capture['copy']['prepared']['file_inventory'],context['read_paths'],messages)
            require(diagnostic['verdict_format']=='invalid' or diagnostic['reads']['rejected_files'])
        else:
            diagnostic=dict(operation='review_failed_inspection_diagnostic_v1' if failed_review else 'review_transport_failure_diagnostic_v1',
                verdict_format='absent_due_to_native_failure' if failed_review else 'absent_due_to_transport',
                manifest_sha256=context['packet']['manifest_sha256'],
                reads=attestation.reads.assessment(capture['copy']['prepared']['file_inventory'],
                    context['packet']['manifest_sha256'],context['read_paths'],messages),
                native_failure_sha256=failure_sha,execution_authorized=False,tests_approved=False,delivery_approval=False)
            if failed_review:
                assessment=diagnostic['reads']
                require(0<assessment['complete_files']<assessment['required_files']
                    and assessment['rejected_files'] and all(r['category']=='file_read_incomplete'
                        for r in assessment['rejected_files']))
                diagnostic['native_failure_cause']='not_proven'
                diagnostic['changed_condition']='independently_qualified_different_worker_profile'
        payload_sha=hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()
        proofs=[p for p in proofs if p.get('request_id')==previous_request and p.get('payload_sha256')==payload_sha
            and p.get('worker_image')==payload['Image'] and p.get('normalized_differences')==[] and p.get('docker_status')=='running']
        require(proofs and len({p['container_id'] for p in proofs})==1 and retirement is not None)
        cid=proofs[-1]['container_id']
        require(tuple(retirement)==(cid,b.PREFIX+'-job-'+previous_request,'gone')
            and ((payload['Image']!=qualified['worker_image']) if transport is None else
                (payload['Image']==qualified['worker_image']))
            and b.docker('GET','/containers/'+cid+'/json') is None
            and b.docker('GET','/containers/'+b.PREFIX+'-job-'+previous_request+'/json') is None)
        with b.LOCK,b.db() as con:
            maintenance.transaction(con);initialize(con)
            held=maintenance.current(con)
            require(held and held['stage']=='sealed' and held['drained'] is True and held['operation_id']==operation
                and not con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone()
                and not con.execute('SELECT 1 FROM grants g LEFT JOIN leases l USING(request_id) WHERE g.deadline>? AND '
                    '(g.used=0 OR (g.used=1 AND l.request_id IS NULL))',(time.time(),)).fetchone()
                and previous_request not in b.SESSIONS)
            require(tuple(con.execute('SELECT used,attempt FROM grants WHERE request_id=?',(previous_request,)).fetchone())==(1,1)
                and tuple(con.execute('SELECT status,name FROM leases WHERE request_id=?',(previous_request,)).fetchone())==('closed',b.PREFIX+'-job-'+previous_request))
            require(json.loads((b.STATE/'native.json').read_bytes())==settings
                and tuple(con.execute('SELECT context_sha256,state_sha256 FROM quality_test_reviews WHERE source_task=?',(source,)).fetchone())==
                    (quality.digest(context),quality.digest(state))
                and attestation.stored_row(con,source,previous_request)[1]==quality.digest(old))
            team=con.execute('SELECT state,state_sha256 FROM quality_team_progress WHERE source_task=?',(source,)).fetchone()
            require(team and quality.digest(json.loads(team[0]))==team[1] and json.loads(team[0])['stage']=='technical_blocked')
            new_marker=quality.digest(dict(operation='review_completion_changed_condition_v3',request=request,context_sha256=quality.digest(context)))
            receipt=dict(operation='review_completion_changed_condition_v3',namespace=b.PREFIX,source_task=source,
                issue_id=context['packet']['issue_id'],previous_task=previous_task,previous_request=previous_request,
                previous_identity={k:task.get(k) for k in FIELDS},previous_assignment=state,previous_attestation=old,
                previous_admission_sha256=quality.digest(admission),previous_team=json.loads(team[0]),
                diagnostic=diagnostic,
                retirement=dict(container_id=cid,state='gone',proof_sha256=quality.digest(proofs[-1]),source='controller_retirement_intent'),
                manifest_sha256=context['packet']['manifest_sha256'],context_sha256=quality.digest(context),
                condition_sha256=condition,ordinal=len(previous)+1,new_marker=new_marker,request=request,
                incident_closed=False,model_calls=0,tests_approved=False,delivery_approval=False)
            if not native_failed:receipt['native_output_sha256']=hashlib.sha256(output.encode()).hexdigest()
            else:receipt['native_failure_sha256']=failure_sha
            con.execute('INSERT INTO quality_review_completion_recoveries VALUES(?,?,?,?,?)',
                (source,previous_request,new_marker,json.dumps(receipt,sort_keys=True),quality.digest(receipt)))
            after={**state,'stage':'prepared','completion_marker':new_marker}
            for key in ('request_id','review_task','wakeup_id','deadline'):after.pop(key,None)
            con.execute('UPDATE quality_test_reviews SET state=?,state_sha256=? WHERE source_task=?',
                (json.dumps(after,sort_keys=True),quality.digest(after),source))
            team_after={k:v for k,v in json.loads(team[0]).items() if k not in ('incident','evidence_sha256')}
            now=time.time();team_after.update(stage='review_ready',owner=context['reviewer'],phase_started_at=now,
                phase_deadline=now+1800,alert_due=False,recovering_incident=previous_request)
            con.execute('UPDATE quality_team_progress SET state=?,state_sha256=?,observed_at=? WHERE source_task=?',
                (json.dumps(team_after,sort_keys=True),quality.digest(team_after),now,source))
        return receipt


def activation_ready(b,issue,operation):
    with b.db() as con:
        if not history.exists(con,'quality_review_completion_recoveries'):return False
        sources=con.execute('SELECT DISTINCT source_task FROM quality_review_completion_recoveries').fetchall()
    matching=[records(b,r[0])[-1] for r in sources if records(b,r[0])[-1]['issue_id']==issue]
    if not matching:return False
    require(len(matching)==1);record=matching[0];context,state=review.load(b,record['source_task'])
    require(state['stage']=='prepared' and record['request']['maintenance_operation']==operation)
    marker(b,context,state);qualification(b,record['request']['qualification'],operation)
    if 'transport' in record['request']:
        try:from . import quality_review_capacity_recovery as capacity
        except ImportError:import quality_review_capacity_recovery as capacity
        condition=quality.digest(dict(worker=qualification(b,record['request']['qualification'],operation),
            transport=capacity.validate(b,record['request']['transport'],operation,record['previous_request'])))
        require(condition==record['condition_sha256'])
    else:require(qualification(b,record['request']['qualification'],operation)==record['condition_sha256'])
    require(attestation.load(b,record['source_task'],request_id=record['previous_request'])==record['previous_attestation'])
    return True
