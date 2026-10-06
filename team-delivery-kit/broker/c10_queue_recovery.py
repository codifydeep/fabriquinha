"""Once-only CTO feedback using a replayed immutable queue trace, never approval."""
import copy
import hashlib
import json
from pathlib import Path
import time
import uuid
try:
    import c10_status_admission as status, c10_query_admission as query
    import admission_controls_spike, handoff_runtime
except ImportError:
    from broker import c10_status_admission as status, c10_query_admission as query
    from broker import admission_controls_spike, handoff_runtime


def prepare(state,output,trace):
    intake=state.get('c10_status_queue_intake',{})
    rejected=intake.get('plan_verification',{})
    report=state.get('functional_diagnosis_receipt',{})
    if (state.get('c10_queue_trace_feedback') or state.get('stage')!='blocked'
            or state.get('category')!='c10_status_queue_plan_rejected'
            or state.get('delivery_approval') is not False
            or rejected.get('status')!='rejected'
            or rejected.get('cto_decision_sha256')!=report.get('certificate',{}).get('decision_sha256')
            or not rejected.get('cto_decision_sha256')
            or intake.get('failed_task')!=state.get('author_task')
            or intake.get('snapshot')!=state.get('snapshot')
            or intake.get('validation')!=state.get('validation')):
        raise ValueError('exact rejected readonly CTO plan and unchanged failed snapshot required')
    # Reparse the original complete suite failure. Never trust a summary as a receipt.
    shadow=copy.deepcopy(state);shadow.pop('c10_status_queue_intake',None)
    shadow.update(category='c10_checkpoint_acceptance_failed')
    status.prepare_queue_diagnosis(shadow,output)
    resolutions=[event.get('urls') for event in trace.get('trace',[])
        if event.get('op') in ('oldest','newest')]
    sequence=[['/feedback?q=beta','/feedback?q=gamma','/feedback?q=delta'],
        ['/feedback?q=gamma','/feedback?q=delta'],
        ['/feedback?q=gamma','/feedback?status=open?q=delta','/feedback?status=completed?q=delta'],
        ['/feedback?q=gamma','/feedback?status=open?q=delta']]
    if (trace.get('schema')!='c10-queue-diagnostic-v1'
            or trace.get('test_sha256')!=state['validation']['test_sha256']
            or trace.get('instrumented_program_sha256')!=rejected.get('diagnostic_program_sha256')
            or trace.get('snapshot_modified') is not False or trace.get('functional_green') is not False
            or trace.get('delivery_approval') is not False or trace.get('pending_left')!=1
            or trace.get('remaining_urls')!=['/feedback?q=gamma'] or resolutions[-4:]!=sequence
            or [event['op'] for event in trace['trace'] if event.get('op') in ('oldest','newest')][-4:]
                !=['oldest','newest','newest','newest']):
        raise ValueError('actual immutable trace and observed resolution order required')
    revised=copy.deepcopy(state)
    revised['c10_queue_trace_feedback']={'schema':'c10-queue-trace-feedback-v1',
        'prior_diagnosis':state['functional_diagnosis'],'prior_receipt':revised.pop('functional_diagnosis_receipt'),
        'rejected_plan':rejected,'trace':trace,'trace_sha256':hashlib.sha256(json.dumps(trace,sort_keys=True).encode()).hexdigest(),
        'snapshot':state['snapshot'],'validation':state['validation'],'failed_task':state['author_task'],
        'attempt_limit':1,'author_scope_authorized':False,'delivery_approval':False,'at':time.time()}
    note=('CTO READONLY TRACE-LED REASSESSMENT, ONE ATTEMPT. Read all four files fully. '
        'Previous plan rejected; do NOT repeat it. Fixed readonly replay of this EXACT '
        'snapshot proves issuance/resolution: before negative-control oldest: beta,gamma,delta; '
        'oldest consumes beta; newest consumes delta; gamma remains. Status clicks append '
        'open and completed; newest consumes completed then open, leaving /feedback?q=gamma. '
        'Full259 sole failure: pending_left=1. Earlier current/stale DOM assertions pass. '
        'Previous explanation reversed issuance and proposed awaiting held loadFeedback '
        'before manual resolution, risking deadlock. Diagnose from source AND this trace. '
        'Propose a bounded real response with valid items and flush for the remaining '
        'request, preserving STATUS current/stale observations and final measurement '
        'out.pending_left=pending.length. Scope stays original STATUS534-536 replacement; '
        'no line526 or QUERY/C09/app/preamble/assertions changes. Never clear pending, '
        'discard promises, fake counters, or await a held promise before manual resolution. '
        'Return request_test_revision, optional_files=[], reason DRIVER_OBSERVATION: '
        'with correct queue order, affected scope, real drain/flush and preserved observations; '
        'max1100chars. If unsupported escalate_cto UNRESOLVED:. This is diagnosis only, '
        'NOT author admission/Green/review/approval. No terminal, writes, cap/model change '
        'or CEO technical question. Evidence programSHA='+trace['instrumented_program_sha256']+'.\n'
        'DELIVERY_CURRENT_HARNESS_DIAGNOSIS_V1\nDELIVERY_STRUCTURED_DECISION_V1:technical\n'
        'DELIVERY_TYPED_DECISION_V1\nDELIVERY_TECHNICAL_LENGTH_FEEDBACK_V1\n'
        'DELIVERY_DETERMINISTIC_READ_V1\n'+
        ''.join('DELIVERY_REVIEW_READ_PATH:'+p+'\n' for p in status.delivery.paths()))
    revised['functional_diagnosis']=dict(state['functional_diagnosis'],note=note,
        failure_origin='actual_immutable_queue_trace_feedback',at=time.time())
    revised.update(stage='maintenance_functional_diagnosis_dispatch',
        category='c10_queue_trace_feedback',owner=state.get('owner'),delivery_approval=False)
    return revised


def replay(b,state):
    """Fixed controller operation: no agent-supplied commands, no mutable mount."""
    volume=state['snapshot']['volume']
    labels=b.docker('GET','/volumes/'+volume)['Labels']
    if labels.get('delivery-kit.owner')!=b.OWNER or labels.get('delivery-kit.source-task')!=state['author_task']:
        raise ValueError('owned exact failed snapshot required')
    image=b.docker('GET','/containers/'+b.PREFIX+'-execution-broker-1/json')['Image']
    name=b.PREFIX+'-queue-trace-'+uuid.uuid4().hex[:12]
    labels={'delivery-kit.owner':b.OWNER,'com.docker.compose.project':b.PREFIX,'com.docker.compose.service':'queue-trace'}
    try:
        b.docker('POST','/containers/create?name='+name,dict(Image=image,User='10000:10000',Entrypoint=['python'],
            Cmd=['/c10_queue_trace.py'],Env=['PYTHONDONTWRITEBYTECODE=1','EXPECTED_TEST='+state['validation']['test_sha256']],
            NetworkDisabled=True,Labels=labels,HostConfig=dict(ReadonlyRootfs=True,NetworkMode='none',
                CapDrop=['ALL'],SecurityOpt=['no-new-privileges'],Memory=268435456,PidsLimit=32,
                Tmpfs={'/tmp':'rw,size=16m,mode=1777'},
                Mounts=[dict(Type='volume',Source=volume,Target='/seed',ReadOnly=True)])))
        b.docker('POST','/containers/'+name+'/start');deadline=time.time()+30
        while time.time()<deadline:
            info=b.docker('GET','/containers/'+name+'/json')
            if not info['State']['Running']:
                if info['State']['ExitCode']!=0:raise ValueError('immutable queue replay failed')
                return json.loads(b.docker_stdout(name,limit=16384))
            time.sleep(.2)
        raise TimeoutError('bounded queue replay deadline')
    finally:
        info=b.docker('GET','/containers/'+name+'/json')
        if info and info['Config'].get('Labels')==labels:
            b.docker('DELETE','/containers/'+info['Id']+'?force=true')


def register(b,source):
    with b.LOCK,b.db() as con:
        config,state=map(json.loads,con.execute('SELECT config,state FROM harness_repair_tasks WHERE source_task=?',(source,)).fetchone())
        admission_controls_spike.verify_current(con,config)
        if state.get('c10_queue_trace_feedback'):
            return {'stage':state['stage'],'reused':True,'author_authorized':False}
        settings=json.loads((b.STATE/'native.json').read_text());fx=handoff_runtime.Effects(b,settings)
        query.idle(b,con,fx,settings,state,56)
        failure=state['suite_failure']
        row=con.execute('SELECT output FROM frozen_suite_failures WHERE task_id=? AND output_sha256=?',
            (state['author_task'],failure['output_sha256'])).fetchone()
        if not row:raise ValueError('durable full-suite failure required')
        trace=replay(b,state);revised=prepare(state,row[0],trace)
        con.execute('UPDATE harness_repair_tasks SET state=? WHERE source_task=?',(json.dumps(revised,sort_keys=True),source))
    return {'stage':revised['stage'],'attempt_limit':1,'author_authorized':False,'delivery_approval':False,
        'trace_sha256':revised['c10_queue_trace_feedback']['trace_sha256']}


def reject(state,decision_sha256,reason):
    """Record an explicit technical audit, never rewrite an agent's decision."""
    intake=state.get('c10_queue_trace_feedback',{});report=state.get('functional_diagnosis_receipt',{})
    cert=report.get('certificate',{})
    if (state.get('stage')!='blocked' or state.get('category')!='maintenance_diagnosis_driver_observation'
            or intake.get('plan_verification') or intake.get('author_scope_authorized') is not False
            or cert.get('decision_sha256')!=decision_sha256 or not decision_sha256
            or cert.get('task_id')==intake.get('prior_receipt',{}).get('certificate',{}).get('task_id')
            or cert.get('snapshot')!=state.get('snapshot',{}).get('volume')
            or cert.get('test_sha256')!=state.get('validation',{}).get('test_sha256')
            or intake.get('snapshot')!=state.get('snapshot') or intake.get('validation')!=state.get('validation')
            or not isinstance(reason,str) or not 1<=len(reason)<=700):
        raise ValueError('exact completed trace-feedback decision and explicit rejection required')
    revised=copy.deepcopy(state)
    revised['c10_queue_trace_feedback']['plan_verification']={
        'schema':'c10-queue-trace-plan-audit-v1','status':'rejected',
        'cto_decision_sha256':decision_sha256,'trace_sha256':intake['trace_sha256'],
        'snapshot':state['snapshot'],'validation':state['validation'],'reason':reason,
        'assessment_source':'controller_technical_audit','author_authorized':False,
        'functional_green':False,'delivery_approval':False,'at':time.time()}
    revised.update(category='c10_queue_trace_plan_rejected',delivery_approval=False,
        next_action='Structured event plan bound to actual queue identities; no identical replay or author admission')
    return revised


def record_rejection(b,source,decision_sha256,reason):
    with b.LOCK,b.db() as con:
        config,state=map(json.loads,con.execute('SELECT config,state FROM harness_repair_tasks WHERE source_task=?',(source,)).fetchone())
        admission_controls_spike.verify_current(con,config)
        settings=json.loads((b.STATE/'native.json').read_text());fx=handoff_runtime.Effects(b,settings)
        query.idle(b,con,fx,settings,state,0)
        report=state['functional_diagnosis_receipt']
        task=status.native.task_record(settings,report['certificate']['task_id'],config['cto'])
        try:import harness_repair_task as h
        except ImportError:from broker import harness_repair_task as h
        decision=fx.decision(task);cert=h.qualify_diagnosis(config,state,task,decision,fx.read_evidence(task))
        if status.delivery.qualify_functional_decision(state,decision,cert)!=report:
            raise ValueError('actual completed readonly CTO evidence required')
        if replay(b,state)!=state['c10_queue_trace_feedback']['trace']:
            raise ValueError('immutable trace changed before assessment')
        revised=reject(state,decision_sha256,reason)
        con.execute('UPDATE harness_repair_tasks SET state=? WHERE source_task=?',(json.dumps(revised,sort_keys=True),source))
    return {'stage':revised['stage'],'category':revised['category'],'author_authorized':False,'delivery_approval':False}
