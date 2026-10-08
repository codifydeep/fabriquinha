"""One immutable calibration rejection -> CTO -> peer -> original author.

This is a gate-rework lane, not a retry-budget reset or a new release. Only a
recorded failed calibration can enter; both planners must read the exact frozen
candidate. The author still owes calibration, Red and independent test review.
"""
import hashlib,json,time


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def initialize(con):
    con.execute('CREATE TABLE IF NOT EXISTS calibration_reworks(issue_id TEXT PRIMARY KEY,source_task TEXT,config TEXT,state TEXT)')
    con.execute('CREATE TABLE IF NOT EXISTS calibration_rework_history('
                'issue_id TEXT,source_task TEXT,config TEXT,state TEXT,PRIMARY KEY(issue_id,source_task))')


def instruction(config,state):
    peer=state['stage'].startswith('peer')
    if config.get('post_execution_diagnosis'):
        note=('DELIVERY_STRUCTURED_DECISION_V1:technical\nDELIVERY_CALIBRATION_FAILURE_PLAN_V1\n'
            'DELIVERY_TYPED_DECISION_V1\nDELIVERY_TECHNICAL_LENGTH_FEEDBACK_V1\n'
            'NEW FROZEN CALIBRATION INCIDENT: '+('Independent Tech Lead inspection. ' if peer else 'CTO diagnosis. ')+
            'Read all assigned frozen files completely. The previously sponsored author execution is terminal; '
            'its changed artifact was copied and calibrated by the controller. This is a new measured rejection, '
            'not a retry of its session or proof of product Red. Diagnose the exact remaining defects and propose '
            'a bounded read-only experiment that can validate a remedy on a disposable copy. No shell, edits, '
            'author admission, replay, limit/depth reset, product changes or delivery approval. Preserve every '
            'test method/assertion, baseline byte and acceptance criterion. Both decisions retain a plan only; '
            'execution still requires an evidence-bound qualified experiment and all existing gates. '
            'Return ONLY JSON action=request_test_revision or escalate_cto, reason<=1200 characters, optional_files=[].\n'
            'Previous calibration: '+json.dumps(compact_index(config['post_execution_diagnosis']['previous_diagnostic']),sort_keys=True)+
            '\nCurrent calibration: '+json.dumps(compact_index(diagnostic_index(config['diagnostic'])),sort_keys=True)+
            ('\nCTO proposal: '+json.dumps(state['cto_decision'],sort_keys=True) if peer else '')+
            '\nUnchanged acceptance IDs: '+','.join(sorted(config['criteria']))+'\n'+
            ''.join('DELIVERY_REVIEW_READ_PATH:'+p+'\n' for p in config['paths']))
        if len(note)+100>4000:raise ValueError('bounded post-execution calibration diagnosis required')
        return note
    if config.get('bootstrap_failure'):
        note=('DELIVERY_STRUCTURED_DECISION_V1:technical\nDELIVERY_CALIBRATION_FAILURE_PLAN_V1\n'
            'DELIVERY_TYPED_DECISION_V1\nDELIVERY_TECHNICAL_LENGTH_FEEDBACK_V1\n'
            'PRE-EXECUTION INFRASTRUCTURE INCIDENT: '+('Independent Tech Lead review. ' if peer else 'CTO diagnosis. ')+
            'The latest author worker never started: no ACP initialization or tools executed. '
            'The failed execution and consumed capability remain preserved, never replayed. '
            'The controller verified an unchanged frozen submission and changed startup/retirement infrastructure. '
            'Read all assigned frozen files completely. No shell, edits, Red replay, limit/depth/iteration reset '
            'or delivery approval. Decide whether a fresh independently sponsored bounded V6 correction is '
            'supported, or retain the technical hold. Do not mistake this startup incident for a new functional '
            'or TDD failure. Historical surgical denials remain historical; they did not occur in this execution. '
            'Preserve every assertion, test method, baseline/product byte and acceptance criterion. '
            'Use only the original-author NODE_HARNESS_TEMPLATE scope and inclusive line recipe below. '
            'No author admission yet: controller calibration, full pinned Red, independent review, PR/CI and '
            'same-commit deploy/QA remain mandatory. Return ONLY JSON action=request_test_revision or '
            'escalate_cto, reason<=1200 characters, optional_files=[].\n'
            'Authenticated bootstrap: '+json.dumps(config['bootstrap_failure'],sort_keys=True)+'\n'
            'Bounded recipe: '+json.dumps(config['line_recipe']['recipe'],sort_keys=True)+'\n'+
            (config['bootstrap_infrastructure_note']+'\n' if config.get('bootstrap_infrastructure_note') else '')+
            ('CTO proposal: '+json.dumps(state['cto_decision'],sort_keys=True)+'\n' if peer else '')+
            'Unchanged acceptance IDs: '+','.join(sorted(config['criteria']))+'\n'+
            ''.join('DELIVERY_REVIEW_READ_PATH:'+p+'\n' for p in config['paths']))
        if len(note)+100>4000:raise ValueError('bounded bootstrap diagnosis context required')
        return note
    if config.get('line_recipe_revision'):
        proof=config['line_recipe']
        note=('DELIVERY_STRUCTURED_DECISION_V1:technical\nDELIVERY_CALIBRATION_FAILURE_PLAN_V1\n'
            'DELIVERY_TYPED_DECISION_V1\nDELIVERY_TECHNICAL_LENGTH_FEEDBACK_V1\n'
            'DELIVERY_TEMPLATE_LINES_V6_REPLAN\nDELIVERY_EXECUTED_FAILURES_V1\n'
            'CHANGED-EVIDENCE PLAN ONLY: '+('Independent Tech Lead review. ' if peer else 'CTO diagnosis. ')+
            'Read all frozen original files completely. No shell, edits, Red replay or delivery approval. '
            'The previous two surgical proposals were denied atomically; all original bytes remain unchanged. '
            'The fixed read-only line experiment reproduced the previously validated diagnostic variant without '
            'increasing the file limit. This is a disposable diagnostic copy, never an author submission or Red. '
            'Preserve all test methods/assertions, product/baseline bytes and acceptance. Pending observations '
            'precede settlement; terminal observations must be read afresh AFTER settlement. The original product '
            'lacks the feature: expected Red, not a harness fault. Prior timer claims are not proved by this experiment. '
            'Prior decisions are archived, not replayed. Sponsor only one changed-evidence original-author '
            'NODE_HARNESS_TEMPLATE correction using original inclusive line ranges, not old/new fragments. '
            'Neither decision grants execution, limit/depth reset or recursive revision. Require controller '
            'calibration, full pinned Red, independent test review and all later delivery gates. '
            'Return ONLY JSON action=request_test_revision or escalate_cto, reason<=1200 characters, optional_files=[]. '
            'Check the exact recipe and measured growth; if unsupported retain the hold. No author admission yet.\n'
            'Executed line recipe: '+json.dumps(proof['recipe'],sort_keys=True)+'\nMeasured growth_bytes='+str(proof['growth_bytes'])+
            '; file_bytes='+str(proof['file_bytes'])+'; limit_bytes='+str(proof['file_limit_bytes'])+'\n'
            'Executed original failure: '+json.dumps(config.get('empirical_failure',{'phase':config['diagnostic'].get('phase')}),sort_keys=True)+
            '\nValidated experiment: '+json.dumps(config['experiment_summary'],sort_keys=True)+
            ('\nCTO proposal: '+json.dumps(state['cto_decision'],sort_keys=True) if peer else '')+
            '\nUnchanged acceptance IDs: '+','.join(sorted(config['criteria']))+'\n'+
            ''.join('DELIVERY_REVIEW_READ_PATH:'+p+'\n' for p in config['paths']))
        if len(note)+100>4000:raise ValueError('bounded line replan context too large')
        return note
    if config.get('diagnosis_only'):
        execution=config.get('execution_failure')
        incident=''
        if execution:
            proof=state.get('probe',{}).get('proof',{})
            if (proof.get('all_files_unchanged') is not True
                    or type(proof.get('available_growth_bytes')) is not int):
                raise ValueError('executed immutable byte-budget proof required')
            incident=('NEW EXECUTION FAILURE: both surgical proposals were rejected; all original bytes remain unchanged. '
                'Use original fragments, not rejected replacements; prefer minimal observation expressions. '
                'No larger file limit or unchanged executor retry is authorized. '
                'Native denial categories: '+json.dumps([r['category'] for r in execution['results']])+'\nMeasured file budget: '+
                json.dumps({k:proof[k] for k in ('test_bytes','file_limit_bytes','available_growth_bytes')},sort_keys=True)+'\n')
            empirical=''
            if config.get('evidence_revision'):
                empirical=('DELIVERY_EXECUTED_FAILURES_V1\nExecuted original failure: '+
                    json.dumps({k:config['empirical_failure'][k] for k in ('phase','failed_methods')},sort_keys=True)+
                    '\nSame-snapshot copy: 15 positives and 12 negative controls passed after only refreshing '
                    'terminal observation. Prior timer claims are not proven by this receipt. Reconcile these failed methods '
                    'and experiment, not unsupported theory. Prior decisions are archived, not replayed.\n')
            note=('DELIVERY_STRUCTURED_DECISION_V1:technical\nDELIVERY_CALIBRATION_FAILURE_PLAN_V1\n'
                'DELIVERY_TYPED_DECISION_V1\nDELIVERY_TECHNICAL_LENGTH_FEEDBACK_V1\n'
                'POST-FAILURE PLAN ONLY: '+('Independent Tech Lead review. ' if peer else 'CTO diagnosis. ')+
                'Read every frozen original file completely. No shell, edits, Red replay or delivery approval. '
                'Preserve every test method/assertion, original product, existing tests and all acceptance. '
                'Propose only a bounded NEW harness template correction by the original author. '
                'Pending observations precede settlement; terminal observations must be read afresh after settlement. '
                'The previous successful experiment used a disposable COPY, never an author submission or valid Red. '
                'The original product lacks the new feature: expected Red, not a harness fault. '
                'Neither decision grants execution, reset of limits/depth or recursive revision. '
                'Require controller calibration, full pinned Red, independent test review and all later delivery gates. '
                'Return ONLY JSON action=request_test_revision or escalate_cto, reason<=1200 characters, optional_files=[]. '
                'Explain a minimal exact-fragment proposal and its byte growth; if unsupported retain the hold.\n'+
                incident+empirical+'Prior experiment: '+json.dumps({k:config['experiment_summary'][k] for k in
                    ('hypothesis','original_failures','variant_positive_tests','variant_negative_controls','diagnostic_copy_only')
                    if k in config['experiment_summary']},sort_keys=True)+
                ('\nCTO proposal: '+json.dumps(state['cto_decision'],sort_keys=True) if peer else '')+
                '\nUnchanged acceptance IDs: '+','.join(sorted(config['criteria']))+'\n'+
                ''.join('DELIVERY_REVIEW_READ_PATH:'+p+'\n' for p in config['paths']))
            if len(note)+100>4000:raise ValueError('surgical failure plan context too large')
            return note
        note=('DELIVERY_STRUCTURED_DECISION_V1:technical\nDELIVERY_CALIBRATION_FAILURE_PLAN_V1\n'
            'DELIVERY_TYPED_DECISION_V1\nDELIVERY_TECHNICAL_LENGTH_FEEDBACK_V1\n'
            'POST-FAILURE PLAN ONLY: '+('Independent Tech Lead review of CTO proposal. ' if peer else 'CTO diagnosis. ')+
            'Read every ORIGINAL failed candidate file completely. No shell, edits, Red replay or delivery approval. '
            'The diagnostic experiment used a disposable COPY, not an author submission; it cannot be merged or used as Red. '
            'Propose a distinct bounded original-author correction of the NEW harness; preserve every test method/assertion, '
            'baseline/product bytes and all acceptance. Pending observations precede settlement; terminal observations '
            'must be freshly read after settlement, not copied from pending values. '
            'The original product lacks the new feature, so its behavioral failure is EXPECTED Red. '
            'Require fresh controller calibration, full pinned Red, independent test review and all later delivery gates. '
            'This lane retains a proposal only. Neither decision grants execution, reset of limits/depth or recursive revision. '
            'Return ONLY JSON action=request_test_revision or escalate_cto, reason<=1200 characters, optional_files=[]. '
            'Explain the changed evidence and minimal correction; if uncertain retain the hold with escalate_cto.\n'+
            incident+'Executed experiment: '+json.dumps(config['experiment_summary'],sort_keys=True)+
            '\nOriginal failure: '+json.dumps(config['diagnostic'],sort_keys=True)+
            ('\nCTO proposal: '+json.dumps(state['cto_decision'],sort_keys=True) if peer else '')+
            '\nUnchanged acceptance IDs: '+','.join(sorted(config['criteria']))+'\n'+
            ''.join('DELIVERY_REVIEW_READ_PATH:'+p+'\n' for p in config['paths']))
        if len(note)+100>4000:raise ValueError('failure plan context too large')
        return note
    note=('DELIVERY_STRUCTURED_DECISION_V1:technical\nDELIVERY_CALIBRATION_REWORK_V1\n'
        'DELIVERY_TYPED_DECISION_V1\nDELIVERY_TECHNICAL_LENGTH_FEEDBACK_V1\n'
        'CALIBRATION GATE REWORK: '+('independent Tech Lead inspection of CTO proposal. ' if peer else 'CTO diagnosis. ')+
        'Read every immutable candidate file completely. No shell, edits, Red replay or approval of delivery. '
        'The controller rejected this candidate before Red. Passing the positive reference alone is '
        'insufficient: every negative and background control must also pass. A harness rejection is not product Red. '
        'Diagnose the NEW harness and preserve every existing method/assertion and all original acceptance. '
        'Only the original author may execute a tests-only rework after BOTH independent decisions. '
        'A request sponsors one changed-evidence gate rework, never an identical retry, budget/depth reset, '
        'baseline edit, product edit, merge or homologation.\nEvidence: '+json.dumps(diagnostic_index(config['diagnostic']),sort_keys=True)+
        ('\nCTO proposal: '+json.dumps(state['cto_decision'],sort_keys=True) if peer else '')+
        '\nUnchanged acceptance IDs: '+','.join(sorted(config['criteria']))+
        '\nReturn ONLY JSON action=request_test_revision or escalate_cto, reason<=1200 characters, optional_files=[]. '
        'Explain a concrete observation-preserving correction; if evidence is insufficient escalate, never guess.\n'+
        ''.join('DELIVERY_REVIEW_READ_PATH:'+p+'\n' for p in config['paths']))
    if len(note)+100>4000:raise ValueError('calibration diagnosis context too large')
    return note


def diagnostic_index(diagnostic):
    """Bounded planner facts; complete immutable evidence remains in storage."""
    from service_mode_harness_qualification import CASES
    result={k:diagnostic[k] for k in ('phase','manifest_sha256','test_sha256','positive','background') if k in diagnostic}
    negatives=diagnostic.get('negative_controls')
    if isinstance(negatives,dict):
        required=set(CASES)
        if diagnostic.get('phase')=='background_timer_control':
            from service_mode_timer_background_qualification import INDICATOR_TIMERS
            required.update(INDICATOR_TIMERS)
        expected=dict(tests=1,failures=1,errors=0,skipped=0,unexpected_successes=0,expected_failures=0)
        failed=[case for case in sorted(required) if not isinstance(negatives.get(case),dict)
            or any(negatives[case].get(k)!=v for k,v in expected.items())]
        result.update(negative_controls_total=len(required),negative_controls_detected=len(required)-len(failed),
            undetected_or_invalid_controls=failed)
    return result


def compact_index(index):
    """Keep all numeric/control facts; method names stay in durable evidence."""
    result=dict(index)
    if isinstance(result.get('positive'),dict):
        result['positive']=dict(result['positive'])
        for key in ('failed_methods','errored_methods'):
            names=result['positive'].pop(key,None)
            if isinstance(names,list):result['positive'][key+'_count']=len(names)
    return result


def recover_post_execution_context(config,state):
    if (not config.get('post_execution_diagnosis') or state.get('post_execution_context_recovery')
            or state.get('stage')!='blocked' or state.get('category')!='calibration_rework_rejected'
            or state.get('error_type')!='ValueError' or not state.get('cto_task')
            or state.get('cto_decision',{}).get('action')!='request_test_revision'
            or state.get('peer_wakeup') or state.get('executor') or state.get('binding_recovery')):
        return None
    note=instruction(config,{**state,'stage':'peer_pending'})
    before=config['post_execution_diagnosis']['previous_diagnostic'];current=diagnostic_index(config['diagnostic'])
    old_length=len(note)+sum(len(json.dumps(i,sort_keys=True))-len(json.dumps(compact_index(i),sort_keys=True)) for i in (before,current))
    if old_length+100<=4000:return None
    new={**state,'stage':'peer_pending','post_execution_context_recovery':dict(
        operation='bounded_calibration_summary_v1',previous_state=state,
        previous_note_characters=old_length,note_characters=len(note),
        note_sha256=hashlib.sha256(note.encode()).hexdigest(),
        author_retry_authorized=False,delivery_approval=False)}
    for key in ('category','error_type','owner'):new.pop(key,None)
    return new


def marker(config,role):
    return digest({'source':config['source_task'],'manifest':config['manifest_sha256'],'role':role,
        'operation':'calibration_failure_plan_v1' if config.get('diagnosis_only') else 'calibration_rework_v1',
        'format_revision':config.get('format_revision',0),
        **({'line_recipe_revision':config['line_recipe_revision']} if config.get('line_recipe_revision') else {}),
        **({'evidence_revision':config['evidence_revision']} if config.get('evidence_revision') else {}),
        **({'bootstrap_policy_revision':config['bootstrap_policy_revision']} if config.get('bootstrap_policy_revision') else {})})


def recover_format(config,state,task,reads):
    """One changed-controller-policy recovery; never replay a failed verdict."""
    role='peer' if state.get('peer_wakeup') else 'cto'
    note=task.get('handoff_note') or ''
    if (state.get('stage')!='blocked' or state.get('category')!='calibration_rework_rejected'
            or config.get('format_revision') or state.get('format_recovery')
            or task.get('status')!='failed' or task.get('agent_id')!=config[role]
            or task.get('issue_id')!=config['issue_id'] or task.get('wakeup_id')!=state.get(role+'_wakeup')
            or 'CALIBRATION GATE REWORK' not in note or 'DELIVERY_STRUCTURED_DECISION_V1:technical' not in note
            or 'DELIVERY_TYPED_DECISION_V1' in note
            or any(reads.get(p,{}).get('lines',0)<=0 or reads[p]['lines']!=reads[p].get('total_lines') for p in config['paths'])):
        return None
    changed={**config,'format_revision':1}
    if 'DELIVERY_TYPED_DECISION_V1' not in instruction(changed,{**state,'stage':role+'_pending'}):return None
    receipt=dict(operation='missing_typed_adapter_marker_recovery_v1',task_id=task['id'],
        previous_state=state,previous_note_sha256=hashlib.sha256(note.encode()).hexdigest(),
        read_evidence=reads,decision_replayed=False,author_retry_authorized=False,delivery_approval=False)
    new={**state,'stage':role+'_pending','format_recovery':receipt}
    new.pop(role+'_wakeup',None)
    for key in ('category','error_type','owner','intent_at','at'):new.pop(key,None)
    return changed,new


def decide(config,state,runs,effects,role):
    actor=config[role];wake=state[role+'_wakeup'];tasks=[t for t in runs if t.get('wakeup_id')==wake]
    if not tasks or any(t['status'] in ('queued','dispatched','running') for t in tasks):return None
    if len(tasks)!=1 or tasks[0].get('agent_id')!=actor or tasks[0]['status']!='completed':
        raise ValueError('one completed independent calibration planner required')
    task=tasks[0];decision=effects.decision(task);reads=effects.read_evidence(task)
    if (decision.get('action') not in ('request_test_revision','escalate_cto') or decision.get('optional_files')!=[]
            or not isinstance(decision.get('reason'),str) or not 1<=len(decision['reason'])<=1200
            or any(type(reads.get(p,{}).get('lines')) is not int or reads[p]['lines']<=0
                   or reads[p]['lines']!=reads[p].get('total_lines') for p in config['paths'])):
        raise ValueError('actual complete reads and concrete independent sponsorship required')
    return task['id'],decision


def recover_technical_escalation(config,state,runs,effects):
    """Classify an already executed valid hold; never replay or wake a planner."""
    if (state.get('stage')!='blocked' or state.get('escalation_classification_repair')
            or state.get('category') not in ('calibration_rework_rejected','calibration_failure_plan_rejected','surgical_failure_diagnosis_rejected')
            or state.get('error_type')!='ValueError' or state.get('executor') or state.get('binding_recovery')):
        return None
    role='peer' if state.get('peer_wakeup') else 'cto'
    if not state.get(role+'_wakeup'):return None
    waiting={**state,'stage':role+'_waiting'}
    try:result=decide(config,waiting,runs,effects,role)
    except (ValueError,TypeError,KeyError):return None
    if not result or result[1]['action']!='escalate_cto':return None
    task,value=result
    new={**state,role+'_task':task,role+'_decision':value,
        'category':'calibration_technical_impediment','owner':config['cto'],
        'required_action':'CTO_run_evidence_bound_experiment_and_replan',
        'author_retry_authorized':False,'delivery_approval':False,
        'escalation_classification_repair':dict(previous_state=state,task_id=task,
            operation='executed_technical_hold_classification_v1',decision_replayed=False)}
    new.pop('error_type',None)
    return new


def advance(config,state,runs,effects,persist,now=None):
    now=time.time() if now is None else now
    if state['stage'] in ('blocked','plan_qualified'):return state
    if state['stage']=='author_pending' and (config.get('diagnosis_only') or config.get('post_execution_diagnosis')):
        state={**state,'stage':'plan_qualified','owner':config['cto'],
            'author_retry_authorized':False,'delivery_approval':False,
            'required_action':('execute_read_only_experiment_for_exact_calibration_plan'
                if config.get('post_execution_diagnosis') else 'qualify_bounded_original_author_executor_for_exact_proposal')}
        persist(state)
        return state
    if state['stage']=='author_dispatched':
        # Dispatch acknowledgement is not progress or completion. Observe the
        # exact sponsored execution without creating a replacement wakeup.
        tasks=[t for t in runs if t.get('wakeup_id')==state.get('author_wakeup')]
        if (len(tasks)==1 and tasks[0].get('agent_id')==config['author']
                and tasks[0].get('status')=='failed'):
            state={**state,'stage':'blocked','category':'calibration_author_failed',
                'author_task':tasks[0]['id'],'owner':config['cto'],
                'required_action':'diagnose_author_execution_and_frozen_harness',
                'author_retry_authorized':False,'delivery_approval':False}
            persist(state)
        return state
    role='cto' if state['stage'].startswith('cto') else 'peer' if state['stage'].startswith('peer') else 'author'
    if state['stage'].endswith('_pending') or state['stage'].endswith('_intent'):
        if effects.remaining_calls()<config['minimum_calls']:return state
        first=state['stage'].endswith('_pending')
        if role=='author':
            if not effects.implementation_available(config['issue_id'],config['author']):return state
            source=state['peer_task']
            note=('CONTROLLER INDEPENDENTLY SPONSORED CALIBRATION REWORK. CTO: '+state['cto_decision']['reason']+
                '. Independent Tech Lead: '+state['peer_decision']['reason']+
                '. Resume the assigned workspace; edit ONLY the declared NEW test. Preserve all test '
                'methods/assertions, baseline and product bytes and all acceptance. Repair the harness '
                'observation, not the product. Read and patch the harness; finish after saving and '
                'inspecting the correction. Do not chase Green on the original product: the missing '
                'feature there is EXPECTED Red, not a harness fault. The controller alone runs fixed '
                'positive/negative calibration and the full pinned suite on the immutable submission. '
                'It must capture calibration and genuine Red before independent test review and implementation. '
                'This is one gate rework; no iteration/size/depth change or recursive revision. No promise-only completion.')
            note+='\nDELIVERY_CONTROLLER_CALIBRATION_V1\n'
        else:
            source=config['source_task'] if role=='cto' else state['cto_task'];note=instruction(config,state)
        intent_marker=marker(config,role)
        if first:
            state={**state,'stage':role+'_intent','intent_at':now};persist(state)
        # A persisted ambiguous intent is OBSERVATION ONLY, never another POST.
        wake=effects.ensure_wakeup(config['issue_id'],config[role],source,intent_marker,note,allow_create=first)
        if wake:
            state={**state,role+'_wakeup':wake['id'],'stage':'author_dispatched' if role=='author' else role+'_waiting','at':now}
            persist(state)
        elif now-state['intent_at']>=1800:
            state={**state,'stage':'blocked','category':'calibration_dispatch_unobserved','owner':config['cto']};persist(state)
        return state
    if state['stage'].endswith('_waiting'):
        decision=decide(config,state,runs,effects,role)
        if decision:
            task,value=decision
            if value['action']=='escalate_cto':
                state={**state,role+'_task':task,role+'_decision':value,'stage':'blocked',
                    'category':'calibration_technical_impediment','owner':config['cto'],
                    'required_action':'CTO_run_evidence_bound_experiment_and_replan',
                    'author_retry_authorized':False,'delivery_approval':False}
            else:state={**state,role+'_task':task,role+'_decision':value,'stage':'peer_pending' if role=='cto' else 'author_pending'}
            persist(state)
        elif now-state['at']>=1800:
            state={**state,'stage':'blocked','category':'calibration_planner_deadline','owner':config['cto']};persist(state)
    return state


def handle(b,route,runs,source,prior,effects):
    """Called by the normal supervisor; no operator-triggered wakeup required."""
    if prior['stage'] not in ('test_first_blocked','calibration_rework'):return False
    with b.LOCK:return _handle(b,route,runs,source,prior,effects)


def _handle(b,route,runs,source,prior,effects):
    try:import handoffs,remediation_runtime_guard as guard,harness_qualification as jobs
    except ImportError:from broker import handoffs,remediation_runtime_guard as guard,harness_qualification as jobs
    if prior['stage'] not in ('test_first_blocked','calibration_rework'):return False
    issue=route['issue_id'];key=source['id']
    with b.db() as con:
        initialize(con)
        existing=con.execute('SELECT source_task,config,state FROM calibration_reworks WHERE issue_id=?',(issue,)).fetchone()
    foreign_source=bool(existing and existing[0]!=key)
    rollover=False
    if foreign_source:
        previous_config,previous_state=map(json.loads,existing[1:])
        authors=[r for r in runs if r.get('agent_id')==route.get('author')]
        rollover=(previous_state.get('stage')=='blocked'
            and previous_state.get('category')=='calibration_author_failed'
            and previous_state.get('author_task')==key
            and source.get('wakeup_id')==previous_state.get('author_wakeup')
            and source.get('status')=='failed' and bool(authors)
            and max(authors,key=lambda r:(r.get('created_at') or '',r['id']))['id']==key
            and not previous_config.get('post_execution_diagnosis'))
    if not existing or rollover:
        if prior['stage']!='test_first_blocked':return False
        with b.db() as con:
            if not con.execute("SELECT 1 FROM sqlite_master WHERE name='harness_qualifications'").fetchone():return False
            row=con.execute('SELECT identity,state FROM harness_qualifications WHERE task_id=?',(key,)).fetchone()
            if not row:return False
            identity,held=map(json.loads,row)
            if held.get('stage')!='blocked':return False
            if con.execute('SELECT 1 FROM test_first_red WHERE issue_id=?',(issue,)).fetchone():return False
        if (not route.get('enabled') or source.get('agent_id')!=route['author']
                or source['status'] not in ('completed','failed')
                or any(t['status'] in ('queued','dispatched','running') for t in runs)
                or len({route[k] for k in ('author','cto','techlead')})!=3):return False
        value=guard.qualified(b,issue)
        if not value or not value.get('amendment'):return False
        info=b.docker('GET','/containers/'+held['container_id']+'/json');jobs.verify_job(info,identity['payload'])
        if info['State']['Running'] or info['State']['Status']!='exited' or info['State']['ExitCode']==0:
            raise ValueError('actual failed immutable calibration required')
        volume=b.docker('GET','/volumes/'+identity['volume'])
        labels=volume.get('Labels',{}) if volume else {}
        if labels.get('delivery-kit.owner')!=b.OWNER or labels.get('delivery-kit.test-first-task')!=key:
            raise ValueError('owned frozen calibration candidate required')
        diagnostic=held.get('diagnostic')
        if not diagnostic:
            data=json.loads(prior['data']);sha=(data.get('diagnostic') or {}).get('structured_receipt_sha256')
            with b.db() as con:
                if not con.execute("SELECT 1 FROM sqlite_master WHERE name='calibration_diagnostic_observations'").fetchone():return False
                observed=con.execute('SELECT receipt FROM calibration_diagnostic_observations WHERE source_task=? AND receipt_sha256=?',(key,sha)).fetchone()
            if not observed:return False
            proof=json.loads(observed[0])
            if proof.get('status')!='rejected' or proof.get('delivery_approval') is not False:return False
            diagnostic={k:proof[k] for k in ('phase','manifest_sha256','test_sha256','positive','negative_controls','background') if k in proof}
        if diagnostic.get('manifest_sha256')!=identity['manifest_sha256']:raise ValueError('exact calibration diagnostic manifest required')
        if rollover:
            with b.db() as con:
                checkpoint=con.execute('SELECT receipt FROM failed_test_checkpoint_executions '
                    'WHERE issue_id=? AND source_task=?',(issue,key)).fetchone()
            proof=json.loads(checkpoint[0]) if checkpoint else {}
            if (proof.get('status')!='rejected' or proof.get('delivery_approved') is not False
                    or identity.get('task_id')!=key or identity.get('issue_id')!=issue
                    or any(previous_config[k]!=route[v] for k,v in
                        (('author','author'),('cto','cto'),('peer','techlead')))
                    or previous_config['contract_sha256']!=route['contract_sha256']
                    or previous_config['manifest_sha256']==identity['manifest_sha256']
                    or previous_config['diagnostic'].get('test_sha256')==diagnostic.get('test_sha256')):
                return False
            observed=b.docker_stdout(info['Id'],include_stderr=False,limit=32768)
            if hashlib.sha256(observed.encode()).hexdigest()!=held.get('output_sha256'):
                raise ValueError('new calibration job receipt drift')
        config=dict(issue_id=issue,source_task=key,author=route['author'],cto=route['cto'],peer=route['techlead'],
            manifest_sha256=identity['manifest_sha256'],volume=identity['volume'],diagnostic=diagnostic,
            contract_sha256=route['contract_sha256'],criteria=value['criteria'],minimum_calls=route['minimum_calls'],
            paths=sorted('/evidence/candidate/'+p for p in set(route['test_first_files'])|{'app/static/app.js'}))
        state=dict(stage='cto_pending',delivery_approval=False,revision_depth_reset=False,attempt_limit=1)
        if rollover:
            config['post_execution_diagnosis']=dict(operation='changed_calibration_incident_v1',
                previous_source=existing[0],previous_manifest=previous_config['manifest_sha256'],
                previous_diagnostic=diagnostic_index(previous_config['diagnostic']),
                checkpoint_sha256=digest(proof),author_retry_authorized=False,delivery_approval=False)
        instruction(config,state)
        with b.LOCK,b.db() as con:
            if con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','active','closing')").fetchone():return True
            if rollover:
                current=con.execute('SELECT source_task,config,state FROM calibration_reworks WHERE issue_id=?',(issue,)).fetchone()
                if tuple(current)!=tuple(existing):raise ValueError('calibration incident changed before archival')
                con.execute('INSERT INTO calibration_rework_history VALUES(?,?,?,?)',(issue,*existing))
                con.execute('UPDATE calibration_reworks SET source_task=?,config=?,state=? WHERE issue_id=?',
                    (key,json.dumps(config,sort_keys=True),json.dumps(state,sort_keys=True),issue))
                foreign_source=False
            else:con.execute('INSERT INTO calibration_reworks VALUES(?,?,?,?)',(issue,key,json.dumps(config,sort_keys=True),json.dumps(state,sort_keys=True)))
    else:config,state=map(json.loads,existing[1:])
    recovered=recover_post_execution_context(config,state)
    if recovered:
        state=recovered
        with b.db() as con:
            con.execute('UPDATE calibration_reworks SET state=? WHERE issue_id=?',(json.dumps(state,sort_keys=True),issue))
    if state.get('stage')=='blocked' and not config.get('format_revision'):
        role='peer' if state.get('peer_wakeup') else 'cto'
        candidates=[t for t in runs if t.get('wakeup_id')==state.get(role+'_wakeup') and t.get('agent_id')==config[role]]
        if len(candidates)==1:
            try:import native
            except ImportError:from broker import native
            task=native.task_record(effects.settings,candidates[0]['id'],config[role])
            recovery=recover_format(config,state,task,effects.read_evidence(task))
            if recovery:
                with b.LOCK,b.db() as con:
                    closed=con.execute('SELECT l.status FROM native_bindings n JOIN leases l USING(request_id) '
                        'WHERE n.task_id=? AND n.issue_id=? AND n.agent_id=?',(task['id'],issue,config[role])).fetchall()
                    if len(closed)==1 and closed[0][0]=='closed' and not con.execute(
                            "SELECT 1 FROM leases WHERE status IN ('creating','starting','running','active','closing')").fetchone():
                        config,state=recovery
                        con.execute('UPDATE calibration_reworks SET config=?,state=? WHERE issue_id=?',
                            (json.dumps(config,sort_keys=True),json.dumps(state,sort_keys=True),issue))
    def persist(new):
        with b.db() as con:
            current=handoffs.load(con,key);data=json.loads(current['data'])
            con.execute('UPDATE calibration_reworks SET state=? WHERE issue_id=?',(json.dumps(new,sort_keys=True),issue))
            data['calibration_rework']={'manifest_sha256':config['manifest_sha256'],'state':new}
            data['required_action']='calibration_rework_v1:'+new['stage']
            owner=config['peer'] if new['stage'].startswith('peer') else config['author'] if new['stage'].startswith('author') else config['cto']
            handoffs.save(con,key,issue,'calibration_rework',owner,data,time.time())
    if (not route.get('enabled') or route['contract_sha256']!=config['contract_sha256']
            or any(route[k]!=config[v] for k,v in (('author','author'),('cto','cto'),('techlead','peer')))):return not foreign_source
    if foreign_source:
        # The normal author gates still process this task. Separately update the
        # original coordination record, which otherwise remains dispatched forever.
        if state.get('stage')=='author_dispatched' and source.get('wakeup_id')==state.get('author_wakeup'):
            key=existing[0]
            advance(config,state,runs,effects,persist)
        return False
    try:
        if state.get('stage')=='plan_qualified' and config.get('post_execution_diagnosis'):
            try:import indicator_experiment
            except ImportError:from broker import indicator_experiment
            indicator_experiment.advance(b,config,state,effects,persist)
            return True
        repaired=recover_technical_escalation(config,state,runs,effects)
        if repaired:persist(repaired)
        else:advance(config,state,runs,effects,persist)
    except (ValueError,TypeError,KeyError) as error:
        persist({**state,'stage':'blocked','category':'calibration_rework_rejected','error_type':type(error).__name__,'owner':config['cto']})
    return True


def mounts(b,binding):
    try:import native
    except ImportError:from broker import native
    with b.db() as con:
        initialize(con)
        row=con.execute('SELECT config,state FROM calibration_reworks WHERE issue_id=?',(binding['issue_id'],)).fetchone()
        if not row:return []
        config,state=map(json.loads,row)
        role='cto' if state['stage'].startswith('cto') else 'peer' if state['stage'].startswith('peer') else None
        if not role or config[role]!=binding['agent_id']:return []
        task=con.execute('SELECT task_id FROM native_bindings WHERE request_id=?',(binding['request_id'],)).fetchone()
    if not task:raise ValueError('calibration planner binding required')
    settings=json.loads((b.STATE/'native.json').read_text())
    run=native.task_record(settings,task[0],binding['agent_id'])
    wake=state.get(role+'_wakeup')
    if not wake and state['stage']==role+'_intent':
        intent_marker=marker(config,role)
        observed=native.ensure_task_handoff(settings,config['issue_id'],config[role],
            config['source_task'] if role=='cto' else state['cto_task'],intent_marker,instruction(config,state),allow_create=False)
        wake=observed['id'] if observed else None
    if not wake or run.get('wakeup_id')!=wake:return []
    labels=(b.docker('GET','/volumes/'+config['volume']) or {}).get('Labels',{})
    if labels.get('delivery-kit.owner')!=b.OWNER or labels.get('delivery-kit.test-first-task')!=config['source_task']:
        raise ValueError('calibration immutable snapshot ownership drift')
    return [dict(Type='volume',Source=config['volume'],Target='/evidence/candidate',ReadOnly=True)]
