"""Bound controller experiment memory to subsequent read-only diagnostics.

Native wakeup notes stay small. The broker expands their existing authenticated
failure marker with complete, losslessly encoded evidence at prompt time.
"""
import copy
import hashlib
import json
import time


def decode_receipt(compact):
    proof=copy.deepcopy(compact);encoded=proof['events']
    if encoded.get('encoding')!='lossless-event-dictionary-v1':raise ValueError('qualified event encoding required')
    dictionary=encoded['dictionary'];reports=[]
    for report in encoded['reports']:
        indices=report['event_indices']
        if any(type(i) is not int or not 0<=i<len(dictionary) for i in indices):raise ValueError('exact event references required')
        reports.append({**{k:v for k,v in report.items() if k!='event_indices'},
            'events':[dictionary[i] for i in indices]})
    proof['events']=reports
    return proof


def verify_context(context,source,failure,reference):
    try:import frozen_adjudication_spike as spike
    except ImportError:from broker import frozen_adjudication_spike as spike
    proof=decode_receipt(context['receipt'])
    if (context.get('operation')!='bound_diagnostic_experiment_context_v1'
            or context.get('source_task')!=source or failure.get('source_task')!=source
            or context.get('failure_sha256')!=spike.digest(failure)
            or context.get('proof_sha256')!=reference.get('proof_sha256')
            or spike.digest(proof)!=context['proof_sha256']
            or proof.get('operation')!=spike.OPERATION or proof.get('delivery_approval') is not False
            or proof.get('author_retry_authorized') is not False or proof.get('test_change_authorized') is not False
            or proof.get('tracing_observations_equal') is not True
            or proof.get('suite',{}).get('tests')!=failure.get('tests_executed')
            or proof['suite'].get('failures',0)<1 or proof['suite'].get('errors')!=0
            or proof['suite'].get('skipped')!=0):raise ValueError('source-bound complete nonauthorizing diagnostic context required')
    return proof


def context_for(config,state,data):
    try:import frozen_adjudication_spike as spike
    except ImportError:from broker import frozen_adjudication_spike as spike
    if state.get('stage')!='dispatched':raise ValueError('accepted evidence handoff required')
    proof=spike.validate_pair(config,state['plain'],state['traced'])
    context=dict(operation='bound_diagnostic_experiment_context_v1',source_task=config['source_task'],
        failure_sha256=spike.digest(config['failure']),proof_sha256=spike.digest(proof),receipt=spike.compact_receipt(proof))
    verify_context(context,config['source_task'],data['validation_failure'],data.get('adjudication_spike',{}))
    return context


def recovery_instruction(data,context):
    try:import bound_failure_context
    except ImportError:from broker import bound_failure_context
    paths=sorted(data['validation_failure']['diagnostic_read_files'])
    note=('CTO: YOU ARE THE TECHNICAL DECISION OWNER. Complete controller experiment evidence is now '
        'supplied through authenticated context expansion, not a new test run. Inspect that evidence '
        'and the complete frozen sources. Do not request the same already recorded per-tick trace. '
        'The unrelated service-mode experiment failed; it establishes no product or test defect. '
        'Return request_correction only for a source-supported product fix, or escalate_cto with ONE '
        'precisely missing observation or contract. No test rewrite, author retry, Green, delivery '
        'approval or CEO technical decision. No shell or writes.\n'
        'DELIVERY_STRUCTURED_DECISION_V1:technical\nDELIVERY_TYPED_DECISION_V1\n'
        'DELIVERY_TECHNICAL_FORMAT_FEEDBACK_V1\n'
        'DELIVERY_BOUND_FAILURE_CONTEXT_V1:'+data['source_task']+':'+bound_failure_context.digest(data['validation_failure'])+'\n'
        'DELIVERY_DIAGNOSTIC_EXPERIMENT_CONTEXT_V1:'+context['proof_sha256']+'\n')
    for path in paths:note+='DELIVERY_REVIEW_READ_PATH:/evidence/candidate/'+path+'\n'
    for path in paths:
        if path.startswith('tests/'):note+='DELIVERY_REVIEW_READ_PATH:/evidence/previous/'+path+'\n'
    if len(note)>3500:raise ValueError('bounded diagnostic memory note required')
    return note


def prepare_recovery(row,route,task,binding,decision,reads,context,*,active,pending,consumed):
    data=json.loads(row['data']);failed=data.get('unsupported_experiment_recovery',{})
    paths=['/evidence/candidate/'+p for p in data.get('validation_failure',{}).get('diagnostic_read_files',[])]
    verify_context(context,row['source_task'],data['validation_failure'],data.get('adjudication_spike',{}))
    if (active or pending or consumed or row['stage']!='technical_decision_required'
            or row['owner']!=route['cto'] or data.get('target')!=route['cto'] or not route.get('enabled')
            or data.get('diagnostic_evidence_context') or route['author']==route['cto']
            or task.get('id')!=data.get('recipient_task') or task.get('id')!=failed.get('decision_task')
            or task.get('agent_id')!=route['cto'] or task.get('issue_id')!=row['issue_id']
            or task.get('wakeup_id')!=data.get('wakeup_id') or task.get('status')!='completed'
            or binding.get('status')!='closed' or binding.get('task_id')!=task['id']
            or binding.get('agent_id')!=route['cto'] or binding.get('issue_id')!=row['issue_id']
            or binding.get('scope','').split(':')[-2:]!=['planning',task['id']]
            or decision!=data.get('decision') or decision.get('action')!='escalate_cto'
            or decision.get('optional_files')!=[] or not paths
            or any(reads.get(p,{}).get('lines',0)<=0 or reads[p]['lines']!=reads[p].get('total_lines') for p in paths)):
        raise ValueError('completed unsupported-experiment diagnosis missing durable context required')
    updated=copy.deepcopy(data);updated['diagnostic_evidence_context']=context
    updated['diagnostic_evidence_recovery']=dict(operation='new_durable_experiment_context_v1',
        previous_task=task['id'],previous_wakeup=task['wakeup_id'],proof_sha256=context['proof_sha256'],
        jobs_reexecuted=False,author_retry_authorized=False,test_change_authorized=False,delivery_approval=False)
    updated.update(trigger_task=task['id'],target=route['cto'],dispatch_stage='diagnose_cto',
        diagnostic_revision=data.get('diagnostic_revision','')+':durable-experiment-context-v1',
        instruction=recovery_instruction(updated,context),required_action='CTO adjudicate preserved complete experiment evidence')
    for key in ('recipient_task','wakeup_id','dispatch_marker','dispatched_at','decision','control_error','control_error_count'):
        updated.pop(key,None)
    return updated


def tick(b):
    try:import handoffs,native,handoff_runtime,controller_maintenance
    except ImportError:from broker import handoffs,native,handoff_runtime,controller_maintenance
    settings=json.loads((b.STATE/'native.json').read_text());fx=handoff_runtime.Effects(b,settings)
    with b.db() as c:
        c.execute('CREATE TABLE IF NOT EXISTS diagnostic_evidence_recoveries(source_task TEXT PRIMARY KEY,previous_handoff TEXT,receipt TEXT)')
        if controller_maintenance.current(c):return
        rows=c.execute("SELECT source_task,config,state FROM frozen_adjudication_spikes WHERE json_extract(state,'$.stage')='dispatched'").fetchall()
        recoveries=c.execute('SELECT source_task,receipt FROM diagnostic_evidence_recoveries').fetchall()
    for source,raw_receipt in recoveries:
        with b.db() as c:
            row=handoffs.load(c,source)
            if not row:continue
            data=json.loads(row['data'])
            if data.get('control_error')!="KeyError:'dispatch_marker'":continue
            route=json.loads(c.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(row['issue_id'],)).fetchone()[0])
            active=bool(c.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','active','closing')").fetchone())
        runs=native.issue_task_runs(settings,row['issue_id'])
        try:updated=repair_unmarked_intake(row,json.loads(raw_receipt),route['cto'],active=active,
            pending=any(t.get('status') in ('queued','running','dispatched') for t in runs))
        except ValueError:continue
        with b.LOCK,b.db() as c:
            if not c.in_transaction:c.execute('BEGIN IMMEDIATE')
            if controller_maintenance.current(c) or handoffs.load(c,source)!=row:continue
            if c.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','active','closing')").fetchone():continue
            handoffs.save(c,source,row['issue_id'],'diagnose_cto',route['cto'],updated,time.time(),commit=False)
    for source,raw_config,raw_state in rows:
        with b.db() as c:
            row=handoffs.load(c,source)
            if not row or row['stage']!='technical_decision_required':continue
            data=json.loads(row['data'])
            if data.get('diagnostic_evidence_context') or not data.get('unsupported_experiment_recovery'):continue
            consumed=bool(c.execute('SELECT 1 FROM diagnostic_evidence_recoveries WHERE source_task=?',(source,)).fetchone())
            route=json.loads(c.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(row['issue_id'],)).fetchone()[0])
            active=bool(c.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','active','closing')").fetchone())
            bindings=c.execute('SELECT n.*,l.status FROM native_bindings n JOIN leases l USING(request_id) WHERE n.task_id=?',(data.get('recipient_task'),)).fetchall()
        if len(bindings)!=1 or active or consumed:continue
        try:
            task=native.task_record(settings,data['recipient_task'],route['cto'])
            runs=native.issue_task_runs(settings,row['issue_id'])
            context=context_for(json.loads(raw_config),json.loads(raw_state),data)
            updated=prepare_recovery(row,route,task,dict(bindings[0]),fx.decision(task),fx.read_evidence(task),context,
                active=active,pending=any(t.get('status') in ('queued','running','dispatched') for t in runs),consumed=consumed)
        except (ValueError,KeyError):continue
        with b.LOCK,b.db() as c:
            if not c.in_transaction:c.execute('BEGIN IMMEDIATE')
            if controller_maintenance.current(c) or handoffs.load(c,source)!=row:continue
            if c.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','active','closing')").fetchone():continue
            if c.execute('SELECT 1 FROM diagnostic_evidence_recoveries WHERE source_task=?',(source,)).fetchone():continue
            c.execute('INSERT INTO diagnostic_evidence_recoveries VALUES(?,?,?)',
                (source,json.dumps(row,sort_keys=True),json.dumps(updated['diagnostic_evidence_recovery'],sort_keys=True)))
            # Standard handoff machinery generates marker and durable intent.
            handoffs.save(c,source,row['issue_id'],'diagnose_cto',route['cto'],updated,time.time(),commit=False)


def repair_unmarked_intake(row,receipt,cto,*,active,pending):
    """Repair a proven pre-call KeyError, not an uncertain native POST."""
    data=json.loads(row['data']);context=data.get('diagnostic_evidence_context')
    if (active or pending or row['stage'] not in ('dispatch_intent','technical_decision_required')
            or row['owner']!=cto or data.get('target')!=cto or data.get('dispatch_stage')!='diagnose_cto'
            or data.get('control_error')!="KeyError:'dispatch_marker'" or data.get('context_intake_repair')
            or data.get('dispatch_marker') or data.get('recipient_task') or data.get('wakeup_id')
            or not context or data.get('diagnostic_evidence_recovery')!=receipt
            or receipt.get('operation')!='new_durable_experiment_context_v1'
            or receipt.get('jobs_reexecuted') is not False or receipt.get('delivery_approval') is not False):
        raise ValueError('exact unmarked pre-native context intent required')
    verify_context(context,row['source_task'],data['validation_failure'],data.get('adjudication_spike',{}))
    updated=copy.deepcopy(data)
    updated['context_intake_repair']=dict(operation='unmarked_diagnostic_intake_repair_v1',
        previous_handoff_sha256=hashlib.sha256(json.dumps(row,sort_keys=True).encode()).hexdigest(),
        previous_error=data['control_error'],previous_error_count=data.get('control_error_count'),
        native_post_attempted=False,jobs_reexecuted=False,author_retry_authorized=False,delivery_approval=False)
    for key in ('control_error','control_error_count','dispatch_stage'):
        updated.pop(key,None)
    return updated
