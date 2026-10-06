"""Non-executing structured queue plans; no free-text inference or auto approval."""
import copy
import hashlib
import json
import time
try:
    import c10_queue_recovery as recovery
except ImportError:
    from broker import c10_queue_recovery as recovery


def sha(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()


def unique(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise ValueError('duplicate plan key')
        result[key]=value
    return result


def prepare(state,output,trace):
    prior=state.get('c10_queue_trace_feedback',{});report=state.get('functional_diagnosis_receipt',{})
    audit=prior.get('plan_verification',{})
    if (state.get('c10_event_plan_intake') or state.get('stage')!='blocked'
            or state.get('category')!='c10_queue_trace_plan_rejected'
            or audit.get('status')!='rejected' or prior.get('author_scope_authorized') is not False
            or audit.get('cto_decision_sha256')!=report.get('certificate',{}).get('decision_sha256')
            or prior.get('snapshot')!=state.get('snapshot') or prior.get('validation')!=state.get('validation')
            or prior.get('trace')!=trace or prior.get('trace_sha256')!=sha(trace)
            or state.get('delivery_approval') is not False):
        raise ValueError('exact rejected plan and immutable replay required')
    shadow=copy.deepcopy(state);shadow.pop('c10_status_queue_intake',None)
    shadow.update(category='c10_checkpoint_acceptance_failed')
    recovery.status.prepare_queue_diagnosis(shadow,output)
    revised=copy.deepcopy(state)
    revised['c10_event_plan_intake']={'schema':'c10-event-plan-intake-v1',
        'prior_diagnosis':state['functional_diagnosis'],'prior_receipt':revised.pop('functional_diagnosis_receipt'),
        'seed':{'task_id':state['author_task'],'snapshot':state['snapshot'],'validation':state['validation']},
        'trace':trace,'trace_sha256':sha(trace),'attempt_limit':1,
        'author_scope_authorized':False,'delivery_approval':False,'at':time.time()}
    note=('CTO READONLY STRUCTURED EVENT PLAN, NOT ANOTHER PROSE DIAGNOSIS. '
        'Read all four files fully. Actual full259 only pending_left=1 fails. '
        'Use submit_delivery_decision action=request_test_revision, optional_files=[]. '
        'reason MUST be literal DRIVER_OBSERVATION: followed by ONE strict JSON object '
        '(no prose, fences, duplicates or extra keys; <=1200chars TOTAL). Keys: '
        'schema="queue-event-plan-v1",test_sha256="'+state['validation']['test_sha256']+'",'
        'trace_sha256="'+sha(trace)+'",scope=[534,536],'
        'before_negative=<actual URL array before negative-control oldest>, '
        'before_status=<actual URL array before current-status newest>, '
        'remaining=<actual final URL array>,phase="after_stale_status_observation",'
        'drain={operation:<resolveOldest or resolveNewest>,expected_url:<real remaining URL>,'
        'response:{items:[]}},after=["flush","measure_pending_length"],'
        'preserve=["QUERY","C09","current_status_dom","stale_status_dom"]. '
        'Trace: '+json.dumps(trace,separators=(',',':'))+'. '
        'Choose the remaining request identity from evidence; never reinterpret gamma '
        'as open or discard the unresolved promise. The empty items envelope resolves '
        'a stale request; preserve prior actual current/stale DOM observations. '
        'No awaiting a held promise before manual resolution, queue clearing, fake '
        'counter, line526/app/QUERY/C09/preamble/assertion changes. This plan is DATA; '
        'controller simulates queue identity/order but this is not execution, Green '
        'or review. A valid plan does NOT automatically admit an author. If unsupported '
        'return escalate_cto with UNRESOLVED: and concise evidence instead. '
        'No writes, terminal, approvals, CEO technical question or cap/model change.\n'
        'DELIVERY_CURRENT_HARNESS_DIAGNOSIS_V1\nDELIVERY_STRUCTURED_DECISION_V1:technical\n'
        'DELIVERY_TYPED_DECISION_V1\nDELIVERY_TECHNICAL_LENGTH_FEEDBACK_V1\n'
        'DELIVERY_DETERMINISTIC_READ_V1\n'+
        ''.join('DELIVERY_REVIEW_READ_PATH:'+p+'\n' for p in recovery.status.delivery.paths()))
    revised['functional_diagnosis']=dict(state['functional_diagnosis'],note=note,
        failure_origin='actual_queue_structured_plan',at=time.time())
    revised.update(stage='maintenance_functional_diagnosis_dispatch',category='c10_structured_event_plan_intake',delivery_approval=False)
    return revised


def validate(state,report):
    intake=state['c10_event_plan_intake'];seed=intake['seed']
    cert=report['certificate'];decision=report['decision'];trace=intake['trace']
    if (report.get('classification')!='DRIVER_OBSERVATION' or decision.get('action')!='request_test_revision'
            or decision.get('optional_files')!=[] or not cert.get('task_id')
            or cert['task_id']==intake['prior_receipt']['certificate']['task_id']
            or cert.get('snapshot')!=seed['snapshot']['volume']
            or cert.get('test_sha256')!=seed['validation']['test_sha256']
            or cert.get('decision_sha256')!=sha(decision)
            or state.get('snapshot')!=seed['snapshot'] or state.get('validation')!=seed['validation']
            or sha(trace)!=intake['trace_sha256'] or trace.get('test_sha256')!=seed['validation']['test_sha256']
            or trace.get('pending_left')!=1 or trace.get('functional_green') is not False
            or trace.get('snapshot_modified') is not False or trace.get('delivery_approval') is not False):
        raise ValueError('event_plan_identity_mismatch')
    raw=decision.get('reason','')
    prefix='DRIVER_OBSERVATION:'
    if not isinstance(raw,str) or len(raw)>1200 or not raw.startswith(prefix):
        raise ValueError('event_plan_structured_data_required')
    try:plan=json.loads(raw[len(prefix):],object_pairs_hook=unique,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError('invalid constant')))
    except (ValueError,TypeError):raise ValueError('event_plan_invalid_json') from None
    compiled=intake.get('contract')=='controller_facts_v2'
    if compiled:
        if (not isinstance(plan,dict) or set(plan)!={'schema','trace_sha256','operation'}
                or plan['schema']!='queue-recovery-choice-v2' or plan['trace_sha256']!=intake['trace_sha256']
                or plan['operation'] not in ('resolveOldest','resolveNewest')):
            raise ValueError('event_choice_exact_operation_and_trace_required')
        # Compile only measured facts plus the explicit submitted operation. This
        # does not rewrite the decision, fix a rejected submission or execute it.
        queues=[e['urls'] for e in trace['trace'] if e.get('op') in ('oldest','newest')]
        if len(queues)<4 or len(trace['remaining_urls'])!=1:raise ValueError('event_choice_unbounded_trace')
        plan={'schema':'queue-event-plan-v1','test_sha256':seed['validation']['test_sha256'],
            'trace_sha256':intake['trace_sha256'],'scope':[534,536],
            'before_negative':queues[-4],'before_status':queues[-2],'remaining':trace['remaining_urls'],
            'phase':'after_stale_status_observation','drain':{'operation':plan['operation'],
                'expected_url':trace['remaining_urls'][0],'response':{'items':[]}},
            'after':['flush','measure_pending_length'],
            'preserve':['QUERY','C09','current_status_dom','stale_status_dom']}
    keys={'schema','test_sha256','trace_sha256','scope','before_negative','before_status','remaining','phase','drain','after','preserve'}
    if not isinstance(plan,dict) or set(plan)!=keys:raise ValueError('event_plan_exact_fields_required')
    queues=[e['urls'] for e in trace['trace'] if e.get('op') in ('oldest','newest')]
    if (len(queues)<4 or plan['schema']!='queue-event-plan-v1'
            or plan['test_sha256']!=seed['validation']['test_sha256']
            or plan['trace_sha256']!=intake['trace_sha256'] or plan['scope']!=[534,536]
            or plan['before_negative']!=queues[-4] or plan['before_status']!=queues[-2]
            or plan['remaining']!=trace['remaining_urls']
            or plan['phase']!='after_stale_status_observation'
            or plan['after']!=['flush','measure_pending_length']
            or plan['preserve']!=['QUERY','C09','current_status_dom','stale_status_dom']):
        raise ValueError('event_plan_observation_or_scope_mismatch')
    drain=plan['drain'];pending=list(trace['remaining_urls'])
    if (not isinstance(drain,dict) or set(drain)!={'operation','expected_url','response'}
            or drain['operation'] not in ('resolveOldest','resolveNewest')
            or drain['response']!={'items':[]} or len(pending)!=1):
        raise ValueError('event_plan_bounded_real_response_required')
    resolved=pending.pop(0 if drain['operation']=='resolveOldest' else -1)
    if resolved!=drain['expected_url']:raise ValueError('event_plan_resolved_wrong_request')
    result={'schema':'c10-event-plan-verification-v1','status':'verified_as_plan_only',
        'plan':plan,'plan_sha256':sha(plan),'certificate':cert,'trace_sha256':intake['trace_sha256'],
        'remaining_after_simulation':pending,'author_authorized':False,'functional_green':False,'delivery_approval':False}
    if compiled:result['controller_compiled_facts']=True
    return result


def assess(state,report):
    """Automatic deterministic verdict, retaining even a rejected agent submission."""
    if state['c10_event_plan_intake'].get('verification'):raise ValueError('event plan already assessed')
    revised=copy.deepcopy(state);revised['functional_diagnosis_receipt']=report
    try:verification=validate(state,report)
    except (ValueError,KeyError,TypeError,IndexError) as error:
        verification={'schema':'c10-event-plan-verification-v1','status':'rejected',
            'error':str(error)[:180],'certificate':report.get('certificate',{}),
            'author_authorized':False,'functional_green':False,'delivery_approval':False}
    revised['c10_event_plan_intake']['verification']=verification
    revised.update(stage='blocked',category='c10_event_plan_verified' if verification['status']=='verified_as_plan_only'
        else 'c10_event_plan_rejected',delivery_approval=False,
        next_action='Explicit distinct scoped author admission required' if verification['status']=='verified_as_plan_only'
        else 'Structured plan rejected; preserve evidence and no identical automatic retry')
    return revised


def register(b,source):
    with b.LOCK,b.db() as con:
        config,state=map(json.loads,con.execute('SELECT config,state FROM harness_repair_tasks WHERE source_task=?',(source,)).fetchone())
        recovery.admission_controls_spike.verify_current(con,config)
        if state.get('c10_event_plan_intake'):return {'stage':state['stage'],'reused':True,'author_authorized':False}
        settings=json.loads((b.STATE/'native.json').read_text());fx=recovery.handoff_runtime.Effects(b,settings)
        recovery.query.idle(b,con,fx,settings,state,56)
        report=state['functional_diagnosis_receipt'];task=recovery.status.native.task_record(settings,report['certificate']['task_id'],config['cto'])
        try:import harness_repair_task as h
        except ImportError:from broker import harness_repair_task as h
        decision=fx.decision(task);cert=h.qualify_diagnosis(config,state,task,decision,fx.read_evidence(task))
        if recovery.status.delivery.qualify_functional_decision(state,decision,cert)!=report:
            raise ValueError('actual rejected readonly decision required')
        failure=state['suite_failure'];row=con.execute('SELECT output FROM frozen_suite_failures WHERE task_id=? AND output_sha256=?',
            (state['author_task'],failure['output_sha256'])).fetchone()
        if not row:raise ValueError('durable actual full259 failure required')
        revised=prepare(state,row[0],recovery.replay(b,state))
        con.execute('UPDATE harness_repair_tasks SET state=? WHERE source_task=?',(json.dumps(revised,sort_keys=True),source))
    return {'stage':revised['stage'],'author_authorized':False,'delivery_approval':False}


def reassess_parser(state):
    intake=state.get('c10_event_plan_intake',{});verification=intake.get('verification',{})
    if (state.get('stage')!='blocked' or state.get('category')!='c10_event_plan_rejected'
            or intake.get('prior_parser_verdict') or verification.get('status')!='rejected'
            or verification.get('error')!='event_plan_structured_data_required'
            or not state['functional_diagnosis_receipt']['decision']['reason'].startswith('DRIVER_OBSERVATION:{')):
        raise ValueError('exact whitespace-only parser reassessment required')
    revised=copy.deepcopy(state)
    revised['c10_event_plan_intake']['prior_parser_verdict']=revised['c10_event_plan_intake'].pop('verification')
    return assess(revised,revised['functional_diagnosis_receipt'])


def register_parser_reassessment(b,source):
    with b.LOCK,b.db() as con:
        config,state=map(json.loads,con.execute('SELECT config,state FROM harness_repair_tasks WHERE source_task=?',(source,)).fetchone())
        recovery.admission_controls_spike.verify_current(con,config)
        settings=json.loads((b.STATE/'native.json').read_text());fx=recovery.handoff_runtime.Effects(b,settings)
        recovery.query.idle(b,con,fx,settings,state,0)
        report=state['functional_diagnosis_receipt'];task=recovery.status.native.task_record(settings,report['certificate']['task_id'],config['cto'])
        try:import harness_repair_task as h
        except ImportError:from broker import harness_repair_task as h
        decision=fx.decision(task);cert=h.qualify_diagnosis(config,state,task,decision,fx.read_evidence(task))
        if recovery.status.delivery.qualify_functional_decision(state,decision,cert)!=report:
            raise ValueError('actual unchanged structured submission required')
        if recovery.replay(b,state)!=state['c10_event_plan_intake']['trace']:
            raise ValueError('actual unchanged queue trace required')
        revised=reassess_parser(state)
        con.execute('UPDATE harness_repair_tasks SET state=? WHERE source_task=?',(json.dumps(revised,sort_keys=True),source))
    return {'stage':revised['stage'],'category':revised['category'],'model_calls':0,
        'author_authorized':False,'delivery_approval':False,
        'verification':revised['c10_event_plan_intake']['verification']}


def prepare_fixed_facts(state,output,trace):
    intake=state.get('c10_event_plan_intake',{});report=state.get('functional_diagnosis_receipt',{})
    verification=intake.get('verification',{})
    if (state.get('c10_fixed_facts') or state.get('stage')!='blocked'
            or state.get('category')!='c10_event_plan_rejected'
            or verification.get('status')!='rejected'
            or verification.get('error')!='event_plan_observation_or_scope_mismatch'
            or verification.get('certificate')!=report.get('certificate')
            or report.get('certificate',{}).get('decision_sha256')!=sha(report.get('decision'))
            or intake.get('seed',{}).get('snapshot')!=state.get('snapshot')
            or intake.get('seed',{}).get('validation')!=state.get('validation')
            or intake.get('seed',{}).get('task_id')!=state.get('author_task')
            or intake.get('trace')!=trace or intake.get('trace_sha256')!=sha(trace)
            or state.get('delivery_approval') is not False):
        raise ValueError('unconsumed observation mismatch and exact measured trace required')
    shadow=copy.deepcopy(state);shadow.pop('c10_status_queue_intake',None)
    shadow.update(category='c10_checkpoint_acceptance_failed')
    recovery.status.prepare_queue_diagnosis(shadow,output)
    revised=copy.deepcopy(state)
    revised['c10_fixed_facts']={'prior_intake':intake,'prior_receipt':revised.pop('functional_diagnosis_receipt'),
        'prior_diagnosis':state['functional_diagnosis'],'attempt_limit':1,'author_authorized':False,
        'delivery_approval':False,'at':time.time()}
    revised['c10_event_plan_intake']={'schema':'c10-event-plan-intake-v1','contract':'controller_facts_v2',
        'prior_receipt':report,'seed':intake['seed'],'trace':trace,'trace_sha256':sha(trace),
        'attempt_limit':1,'author_scope_authorized':False,'delivery_approval':False,'at':time.time()}
    note=('CTO READONLY RECOVERY CHOICE. Read all four files completely. '
        'The controller owns and freezes measured queue facts; do NOT regenerate '
        'URL arrays, hashes of files, counters or any implementation. Verified trace '
        'before negative oldest: beta,gamma,delta; oldest consumes beta, newest delta. '
        'Before current status newest: gamma,open,completed; newest completed then '
        'newest open leaves only /feedback?q=gamma. Full259 only pending1 fails. '
        'Proposed safe scope: original STATUS534-536 replacement, AFTER the stale-status '
        'DOM observation, resolve the actual remaining gamma request using {items:[]}, '
        'flush, measure pending.length. Preserve all prior current/stale DOM reports, '
        'QUERY/C09/preamble/assertions/product. Confirm from source the remaining '
        'response is stale and cannot repaint the current status. Choose ONLY the '
        'real resolver: resolveOldest or resolveNewest (one pending request). '
        'submit_delivery_decision action=request_test_revision,optional_files=[], '
        'reason=DRIVER_OBSERVATION: followed by strict JSON with EXACTLY THREE keys: '
        '{"schema":"queue-recovery-choice-v2","trace_sha256":"'+sha(trace)+'",'
        '"operation":<your chosen resolver string>}. No prose or extra fields. '
        'Controller compiles observed facts plus YOUR explicit operation, validates '
        'identity/order, but never executes or approves this data. If source does '
        'not support this drain, escalate_cto with UNRESOLVED: and concise reason. '
        'No queue clearing, fake counters, awaiting held promises before resolution, '
        'writes, shell, author admission, Green, review, cap/model change or CEO '
        'technical questions. This is a changed contract, not a retry of rejected data.\n'
        'DELIVERY_CURRENT_HARNESS_DIAGNOSIS_V1\nDELIVERY_STRUCTURED_DECISION_V1:technical\n'
        'DELIVERY_TYPED_DECISION_V1\nDELIVERY_TECHNICAL_LENGTH_FEEDBACK_V1\n'
        'DELIVERY_DETERMINISTIC_READ_V1\n'+
        ''.join('DELIVERY_REVIEW_READ_PATH:'+p+'\n' for p in recovery.status.delivery.paths()))
    revised['functional_diagnosis']=dict(state['functional_diagnosis'],note=note,
        failure_origin='controller_owned_queue_facts',at=time.time())
    revised.update(stage='maintenance_functional_diagnosis_dispatch',category='c10_fixed_facts_choice_intake',delivery_approval=False)
    return revised


def register_fixed_facts(b,source):
    with b.LOCK,b.db() as con:
        config,state=map(json.loads,con.execute('SELECT config,state FROM harness_repair_tasks WHERE source_task=?',(source,)).fetchone())
        recovery.admission_controls_spike.verify_current(con,config)
        if state.get('c10_fixed_facts'):return {'stage':state['stage'],'reused':True,'author_authorized':False}
        settings=json.loads((b.STATE/'native.json').read_text());fx=recovery.handoff_runtime.Effects(b,settings)
        recovery.query.idle(b,con,fx,settings,state,56)
        report=state['functional_diagnosis_receipt'];task=recovery.status.native.task_record(settings,report['certificate']['task_id'],config['cto'])
        try:import harness_repair_task as h
        except ImportError:from broker import harness_repair_task as h
        decision=fx.decision(task);cert=h.qualify_diagnosis(config,state,task,decision,fx.read_evidence(task))
        if recovery.status.delivery.qualify_functional_decision(state,decision,cert)!=report:
            raise ValueError('actual preserved rejected structured submission required')
        failure=state['suite_failure'];row=con.execute('SELECT output FROM frozen_suite_failures WHERE task_id=? AND output_sha256=?',
            (state['author_task'],failure['output_sha256'])).fetchone()
        if not row:raise ValueError('durable actual full259 failure required')
        revised=prepare_fixed_facts(state,row[0],recovery.replay(b,state))
        con.execute('UPDATE harness_repair_tasks SET state=? WHERE source_task=?',(json.dumps(revised,sort_keys=True),source))
    return {'stage':revised['stage'],'attempt_limit':1,'author_authorized':False,'delivery_approval':False}
