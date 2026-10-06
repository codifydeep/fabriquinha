"""One changed-contract C10 admission; no reset of prior executions or approval."""
import copy
import hashlib
import json
import re
import time
try:
    import maintenance_delivery as delivery
    import native,handoff_runtime,admission_controls_spike
except ImportError:
    from broker import maintenance_delivery as delivery
    from broker import native,handoff_runtime,admission_controls_spike

FLAGS=('actual_registry','actual_default_selection','actual_acp_selection',
    'readless_edit_denied','generic_write_and_terminal_denied','direct_handler_fenced',
    'invalid_syntax_preserves_bytes','outside_driver_change_preserves_bytes',
    'test_weakening_preserves_bytes','stale_edit_denied','fixed_node_check','credentials_absent',
    'line_range_registry_qualified','line_range_proxy_schema_qualified','line_range_atomic_rejection',
    'line_range_duplicate_selection','line_range_stale_denied','bounded_node_feedback_acp_visible',
    'identical_syntax_replay_denied','fresh_process_syntax_replay_denied',
    'rejection_persistence_worker_private','changed_proposal_accepted')


def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()


def rejection_receipts(messages,source_sha):
    """Recheck actual complete native messages, never model summary claims."""
    uses=[m for m in messages if m.get('type')=='tool_use' and m.get('tool')=='surgical_test_edit']
    if len(uses)!=2:raise ValueError('two actual syntax rejection proposals required')
    receipts=[]
    for use in uses:
        args=use.get('input')
        if (not isinstance(args,dict) or args.get('path')!='/workspace/tests/test_incremental_u3.py'
                or args.get('expected_sha256')!=source_sha):
            raise ValueError('exact prior surgical source required')
        results=[m for m in messages if m.get('type')=='tool_result'
            and m.get('tool')=='surgical_test_edit' and m.get('call_id')==use.get('call_id')]
        if len(results)!=1:raise ValueError('one actual tool result per proposal required')
        result=results[0];output=result.get('output')
        if (result.get('output_truncated') is not False or not isinstance(output,str)
                or re.findall(r'surgical_edit_rejected:([a-z_]+):',output)!=['driver_syntax_invalid']):
            raise ValueError('complete syntax rejection result required')
        receipts.append({'call_id':use['call_id'],'proposal_sha256':digest(args),
            'output_sha256':hashlib.sha256(output.encode()).hexdigest()})
    if receipts[0]['call_id']==receipts[1]['call_id'] or receipts[0]['proposal_sha256']!=receipts[1]['proposal_sha256']:
        raise ValueError('exact identical rejected proposals required')
    return receipts


def prepare(config,state,task,messages,proof,remaining):
    """Pure fail-closed admission; caller verifies runtime, ownership and CTO reads."""
    if state.get('c10_syntax_recovery'):raise ValueError('C10 syntax recovery already consumed')
    current=state.get('current_execution_result',{});plan=state.get('c10_diagnosis',{})
    guard=state.get('staged',{}).get('driver_guard',{})
    outcome=plan.get('author_outcome',{});diagnostic=outcome.get('proposal_diagnostic',{})
    seed=delivery.fragment_seed(state)
    report=state['functional_diagnosis_receipt'];cert=report['certificate'];audit=plan.get('plan_verification',{})
    if (state.get('stage')!='blocked' or state.get('category')!='unchanged_functional_driver'
            or task.get('status')!='completed' or task.get('id')!=state.get('author_task')
            or task.get('agent_id')!=config['author'] or task.get('issue_id')!=state['issue_id']
            or task.get('wakeup_id')!=state['wakeup_id'] or config['author']==config['cto']
            or current.get('category')!='identical_syntax_rejections' or current.get('task_id')!=task['id']
            or current.get('accepted_edits')!=0 or current.get('files_changed_from_seed') is not False
            or current.get('suite_reexecuted') is not False or current.get('retry_authorized') is not False
            or plan.get('author_scope_authorized') is not True or plan.get('authorized_phase')!='C10'
            or state['functional_fragment_recovery'].get('scope')!='response_envelope_c10_reviewed'
            or state['validation']!=seed['validation'] or plan.get('seed')!=seed
            or plan.get('c09_evidence',{}).get('c09_status')!='passed_in_actual_full_suite'
            or audit.get('verified') is not True or audit.get('certificate')!=cert
            or audit.get('snapshot')!=seed['snapshot'] or audit.get('validation')!=seed['validation']
            or audit.get('scope')!=[500,553] or audit.get('bare_array_response_lines')!=[512,515,528,531]
            or audit.get('real_filter_ids')!=['filter-open','filter-completed']
            or outcome.get('task_id')!=task['id'] or outcome.get('snapshot')!=state['snapshot']
            or outcome.get('validation')!=state['validation'] or outcome.get('suite_reexecuted') is not False
            or diagnostic.get('source_sha256')!=seed['validation']['test_sha256']
            or diagnostic.get('files_modified') is not False or diagnostic.get('application_executed') is not False
            or diagnostic.get('delivery_approval') is not False
            or type(remaining) is not int or remaining<48):
        raise ValueError('exact unchanged C10 evidence and independent authority required')
    image=proof.get('worker_image')
    if (proof.get('schema')!='surgical-driver-registry-probe-v3' or proof.get('status')!='passed'
            or proof.get('protocol')!='typed_driver_lines_v4' or proof.get('network')!='none'
            or proof.get('uid')!=10000 or proof.get('model_calls')!=0 or proof.get('delivery_approval') is not False
            or not isinstance(image,str) or not re.fullmatch('sha256:[0-9a-f]{64}',image)
            or image==guard.get('worker_image') or any(proof.get(k) is not True for k in FLAGS)):
        raise ValueError('different qualified immutable syntax feedback worker required')
    actual=rejection_receipts(messages,seed['validation']['test_sha256'])
    proposals=diagnostic.get('proposals',[])
    if (len(proposals)!=2 or any(p.get('proposal_sha256')!=actual[i]['proposal_sha256']
            or p.get('node_valid') is not False or p.get('node_line')!=144
            or p.get('c09_prefix_preserved') is not True or p.get('protected_suffix_preserved') is not True
            or p.get('ranges')!=[[534,536],[537,537]] for i,p in enumerate(proposals))):
        raise ValueError('exact preserved syntax and scope diagnostics required')
    state=copy.deepcopy(state)
    scope_id=digest({'failed_task':task['id'],'seed':seed,'qualification':proof,'contract_revision':'c10-query-status-syntax-v1'})
    state['c10_syntax_recovery']={'scope_id':scope_id,'failed_task':task['id'],
        'prior_wakeup':state['wakeup_id'],'prior_scope':state['functional_fragment_recovery'],
        'prior_guard':state['staged']['driver_guard'],'prior_result':state.pop('current_execution_result'),
        'prior_snapshot':state['snapshot'],'prior_validation':state['validation'],
        'prior_author_outcome':outcome,'native_rejections':actual,'qualification':proof,
        'cto_certificate':cert,'seed':seed,'attempt_limit':1,'delivery_approval':False,'at':time.time()}
    state['functional_fragment_recovery']=dict(state['functional_fragment_recovery'],
        scope='response_envelope_c10_syntax_feedback',instruction_revision=5,failed_task=task['id'],
        diagnostics={'c09_passed':True,'tests_executed':259,'prior_driver_line':144,
            'prior_syntax_category':'missing_parenthesis','prior_ranges':[[534,536],[537,537]],
            'missing_query_response_ranges':[512,515,528,531],'prior_proposal_sha256':actual[0]['proposal_sha256']})
    state['staged']['driver_guard']=dict(state['staged']['driver_guard'],
        qualification=proof,worker_image=image,line_ranges=True,syntax_feedback=True)
    state.update(stage='checkpoint_dispatch_intent',category='qualified_c10_syntax_recovery',delivery_approval=False,at=time.time())
    note=delivery.functional_correction_note(state)
    # Native unit-start adds its own marker and Source UUID. Validate the wire
    # instruction, not just the unwrapped author contract, before any admission.
    wrapped=('DELIVERY_UNIT_START '+'0'*64+'\nSource: '+'0'*36+'\n'+note).strip()
    # Multica additionally adds event context to task.handoff_note. Keep a
    # bounded reserve rather than relying on the API instruction limit alone.
    if len(wrapped)+512>4000:raise ValueError('bounded wrapped C10 recovery handoff required')
    state['c10_syntax_recovery']['note_sha256']=hashlib.sha256(note.encode()).hexdigest()
    state['c10_syntax_recovery']['wrapped_note_characters']=len(wrapped)
    return state,seed


def prepare_bootstrap(config,state,task,messages,errors,lease,remaining):
    """One infrastructure-only recovery after zero-tool pre-worker failure."""
    prior=state.get('c10_syntax_recovery',{})
    if state.get('c10_bootstrap_recovery'):raise ValueError('C10 bootstrap recovery already consumed')
    if (not prior or state.get('stage')!='blocked' or state.get('category')!='maintenance_inspection_failed'
            or state.get('error_reason')!='author execution failed'
            or task.get('id')!=state['author_task'] or task.get('status')!='failed'
            or task.get('agent_id')!=config['author'] or task.get('issue_id')!=state['issue_id']
            or task.get('wakeup_id')!=state['wakeup_id']
            or task.get('error')!='hermes initialize failed: hermes process exited' or messages!=[]
            or prior.get('attempt_limit')!=1 or state['functional_fragment_recovery'].get('scope')!='response_envelope_c10_syntax_feedback'
            or prior.get('qualification')!=state['staged']['driver_guard']['qualification']
            or lease.get('status')!='failed' or lease.get('scenario')!='acp-session'
            or errors!=[{'operation':'worker_submit','category':'bootstrap:broker_internal'}]
            or not isinstance(task.get('handoff_note'),str) or not 4000<len(task['handoff_note'])<=4512
            or type(remaining) is not int or remaining<48):
        raise ValueError('exact zero-tool pre-worker bootstrap failure required')
    seed=delivery.fragment_seed(state)
    if state['validation']!=prior['prior_validation'] or seed!=prior['seed']:
        raise ValueError('unchanged diagnosed C09 seed required')
    result=copy.deepcopy(state)
    note=delivery.functional_correction_note(result)
    wrapped=('DELIVERY_UNIT_START '+'0'*64+'\nSource: '+'0'*36+'\n'+note).strip()
    note_sha=hashlib.sha256(note.encode()).hexdigest()
    if (len(wrapped)+512>4000 or note_sha==prior['note_sha256']
            or note!=delivery.functional_correction_note(json.loads(json.dumps(result,sort_keys=True)))):
        raise ValueError('changed canonical bounded bootstrap contract required')
    result['c10_bootstrap_recovery']={'failed_task':task['id'],'failed_wakeup':state['wakeup_id'],
        'prior_note_sha256':prior['note_sha256'],'prior_wrapped_note_characters':prior['wrapped_note_characters'],
        'actual_native_note_characters':len(task['handoff_note']),
        'actual_native_note_sha256':hashlib.sha256(task['handoff_note'].encode()).hexdigest(),
        'broker_errors':errors,'lease':lease,'tool_messages':0,'author_tools_executed':False,
        'infrastructure_only':True,'attempt_limit':1,'delivery_approval':False,'at':time.time()}
    result['c10_syntax_recovery']=dict(prior,note_sha256=note_sha,wrapped_note_characters=len(wrapped))
    result.pop('error_type',None);result.pop('error_reason',None)
    result.update(stage='checkpoint_dispatch_intent',category='c10_canonical_bootstrap_recovery',delivery_approval=False,at=time.time())
    return result,seed


def register_bootstrap(b,source):
    with b.LOCK,b.db() as con:
        config,state=map(json.loads,con.execute('SELECT config,state FROM harness_repair_tasks WHERE source_task=?',(source,)).fetchone())
        admission_controls_spike.verify_current(con,config)
        if state.get('c10_bootstrap_recovery'):return {'stage':state['stage'],'reused':True,'delivery_approval':False}
        if con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone():raise ValueError('idle bootstrap recovery required')
        settings=json.loads((b.STATE/'native.json').read_text());fx=handoff_runtime.Effects(b,settings)
        if any(t.get('status') in ('queued','dispatched','running') for t in native.issue_task_runs(settings,state['issue_id'])):
            raise ValueError('idle native bootstrap required')
        task=native.task_record(settings,state['author_task'],config['author'])
        rows=con.execute('SELECT n.request_id,n.agent_id,l.status,l.scenario FROM native_bindings n JOIN leases l USING(request_id) WHERE n.task_id=?',(task['id'],)).fetchall()
        if len(rows)!=1 or rows[0]['agent_id']!=config['author']:raise ValueError('exact failed bootstrap binding required')
        lease=dict(rows[0]);errors=[dict(r) for r in con.execute('SELECT operation,category FROM broker_errors WHERE request_id=?',(lease['request_id'],))]
        revised,seed=prepare_bootstrap(config,state,task,native.task_messages(settings,task['id']),errors,lease,fx.remaining_calls())
        info=b.docker('GET','/containers/'+b.PREFIX+'-job-'+lease['request_id']+'/json')
        if info:raise ValueError('bootstrap job must be absent')
        cert=state['functional_diagnosis_receipt']['certificate']
        cto=native.task_record(settings,cert['task_id'],config['cto'])
        try:import harness_repair_task as h
        except ImportError:from broker import harness_repair_task as h
        diagnosed=dict(state,snapshot=state['functional_diagnosis']['snapshot'],validation=state['functional_diagnosis']['validation'])
        if h.qualify_diagnosis(config,diagnosed,cto,fx.decision(cto),fx.read_evidence(cto))!=cert:
            raise ValueError('existing CTO authority drift')
        image=revised['staged']['driver_guard']['worker_image']
        if b.docker('GET','/images/'+image+'/json')['Id']!=image:raise ValueError('qualified worker missing')
        try:import driver_checkpoint_policy as policy
        except ImportError:from broker import driver_checkpoint_policy as policy
        policy.select(config,dict(revised,stage='awaiting_author'),revised['issue_id'],task)
        trial=json.loads(con.execute('SELECT config FROM test_revision_trials WHERE issue_id=?',(state['issue_id'],)).fetchone()[0])
        if trial.get('maintenance_seed')!={'source':source,'receipt':seed}:raise ValueError('registered immutable seed drift')
        con.execute('UPDATE harness_repair_tasks SET state=? WHERE source_task=?',(json.dumps(revised,sort_keys=True),source))
    return {'stage':revised['stage'],'infrastructure_only':True,'attempt_limit':1,'delivery_approval':False}


def prepare_decomposition(config,state,task,messages,remaining):
    """Escalate consumed author scope to a new readonly CTO planning execution."""
    if state.get('c10_decomposition'):raise ValueError('C10 decomposition already requested')
    incident=state.get('c10_syntax_recovery',{});outcome=incident.get('author_outcome',{})
    current=state.get('current_execution_result',{})
    seed=delivery.fragment_seed(state)
    if (state.get('stage')!='blocked' or state.get('category')!='unchanged_functional_driver'
            or task.get('status')!='completed' or task.get('id')!=state['author_task']
            or task.get('agent_id')!=config['author'] or task.get('issue_id')!=state['issue_id']
            or task.get('wakeup_id')!=state['wakeup_id'] or config['cto']==config['author']
            or outcome.get('task_id')!=task['id'] or outcome.get('snapshot')!=state['snapshot']
            or outcome.get('validation')!=state['validation'] or outcome.get('accepted_edits')!=0
            or outcome.get('files_changed_from_seed') is not False or outcome.get('suite_reexecuted') is not False
            or outcome.get('syntax_feedback_visible') is not True or outcome.get('identical_replay_blocked') is not True
            or current.get('category')!='syntax_rejection_then_replay_block' or current.get('retry_authorized') is not False
            or seed!=incident.get('seed') or seed['validation']!=state['validation']
            or type(remaining) is not int or remaining<56):
        raise ValueError('exact consumed unchanged C10 scope and diagnosis reserve required')
    uses=[m for m in messages if m.get('type')=='tool_use' and m.get('tool')=='surgical_test_edit']
    actual=[]
    for use in uses:
        args=use.get('input');result=[m for m in messages if m.get('type')=='tool_result'
            and m.get('tool')=='surgical_test_edit' and m.get('call_id')==use.get('call_id')]
        if (not isinstance(args,dict) or args.get('path')!='/workspace/tests/test_incremental_u3.py'
                or args.get('expected_sha256')!=seed['validation']['test_sha256']
                or len(result)!=1 or result[0].get('output_truncated') is not False
                or not isinstance(result[0].get('output'),str)):
            raise ValueError('actual complete C10 rejection evidence required')
        output=result[0]['output']
        actual.append({'call_id':use['call_id'],'proposal_sha256':digest(args),
            'output_sha256':hashlib.sha256(output.encode()).hexdigest(),
            'category':re.findall(r'surgical_edit_rejected:([a-z_]+):',output),
            'driver_line':re.findall(r'driver_line=(\d+)',output),
            'syntax_category':re.findall(r'syntax_category=([a-z_]+)',output),
            'ranges':[[e['start_line'],e['end_line']] for e in args['edits']]})
    if (len(actual)!=2 or actual!=outcome.get('tool_receipts')
            or [r['category'] for r in actual]!=[['driver_syntax_invalid'],['identical_rejected_proposal']]
            or actual[0]['proposal_sha256']!=actual[1]['proposal_sha256']
            or actual[0]['driver_line']!=['137'] or actual[0]['syntax_category']!=['unexpected_token']):
        raise ValueError('exact observed syntax feedback and blocked replay required')
    note=('CTO READONLY C10 DECOMPOSITION. Read all four mounted files completely. '
        'Current snapshot is unchanged and Python/Node syntax VALID. Actual earlier '
        '259-test suite proved C09 passed; C10 failed. Latest author attempted query '
        'payloads AND status callbacks together, producing invalid JS at DRIVER_BODY '
        'line137 (unexpected_token). It repeated the proposal, and the handler denied '
        'identical_rejected_proposal. Neither proposal was written; no new suite ran. '
        'Do not label the preserved valid source as syntactically broken or repeat '
        'the consumed author scope. Plan TWO SMALL CHECKPOINTS from source evidence: '
        'QUERY: wrap only the existing bare-array query responses at FILE lines '
        '512/515/528/531 as items envelopes; do not change promise flow, C10STATUS, '
        'C09, fixtures, assertions or product. Specify how actual query observations '
        'and the complete259-test run prove this partial checkpoint, while unresolved '
        'status prevents final approval. STATUS: separately extend the C10STATUS '
        'placeholder with real filter-open/filter-completed actions, request URLs, '
        'current then stale response observations and final pending_left. Identify '
        'exact original promise boundaries and a balanced minimal insertion strategy '
        'that preserves enclosing closures; not another combined rewrite. Each '
        'checkpoint needs its own frozen hash, validation and independently qualified '
        'handoff; never treat partial progress as full-suite Green or delivery. '
        'All edits limited to original C10 lines500-553, preserve verified C09, '
        'preamble, every Python test body/assertion and discovery; maximum4 V4 ranges, '
        '4096bytes per replacement, final32768bytes. Diagnose from immutable reads '
        'only; no terminal, edits, administrative tools, approvals, larger budgets '
        'or technical questions to CEO. Return concise complete PROSE, target650chars, '
        'maximum900, action=request_test_revision, reason=DRIVER_OBSERVATION: with '
        'QUERY and STATUS scopes plus acceptance gates; optional_files=[]. If not '
        'supported return escalate_cto with UNRESOLVED:. No author is authorized by '
        'this planning task.\nDELIVERY_CURRENT_HARNESS_DIAGNOSIS_V1\n'
        'DELIVERY_STRUCTURED_DECISION_V1:technical\nDELIVERY_TYPED_DECISION_V1\n'
        'DELIVERY_TECHNICAL_LENGTH_FEEDBACK_V1\nDELIVERY_DETERMINISTIC_READ_V1\n'+
        ''.join('DELIVERY_REVIEW_READ_PATH:'+p+'\n' for p in delivery.paths()))
    if len(note)>3400:raise ValueError('bounded decomposition diagnosis required')
    revised=copy.deepcopy(state)
    revised['c10_decomposition']={'failed_task':task['id'],'failed_wakeup':state['wakeup_id'],
        'current_seed':{'task_id':task['id'],'snapshot':state['snapshot'],'validation':state['validation'],'checkpoint':2},
        'c09_evidence':state['c10_diagnosis']['c09_evidence'],'native_rejections':actual,
        'prior':{k:state.get(k) for k in ('functional_diagnosis','functional_diagnosis_receipt',
            'functional_correction','functional_fragment_recovery','diagnosis','current_execution_result')},
        'attempt_limit':1,'author_scope_authorized':False,'delivery_approval':False,'at':time.time()}
    revised.pop('functional_diagnosis_receipt',None)
    revised['functional_diagnosis']={'author_task':task['id'],'snapshot':state['snapshot'],
        'validation':state['validation'],'failure':state['c10_diagnosis']['c09_evidence']['full_suite_failure'],
        'failure_origin':'historical_c09_progress_not_latest_execution','note':note,'attempt_limit':1,'at':time.time()}
    revised.update(stage='maintenance_functional_diagnosis_dispatch',category='c10_checkpoint_decomposition',
        owner=config['cto'],delivery_approval=False,at=time.time())
    return revised


def register_decomposition(b,source):
    with b.LOCK,b.db() as con:
        config,state=map(json.loads,con.execute('SELECT config,state FROM harness_repair_tasks WHERE source_task=?',(source,)).fetchone())
        admission_controls_spike.verify_current(con,config)
        if state.get('c10_decomposition'):return {'stage':state['stage'],'reused':True,'author_scope_authorized':False}
        if con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone():raise ValueError('idle decomposition required')
        settings=json.loads((b.STATE/'native.json').read_text());fx=handoff_runtime.Effects(b,settings)
        if any(t.get('status') in ('queued','dispatched','running') for t in native.issue_task_runs(settings,state['issue_id'])):
            raise ValueError('idle native decomposition required')
        task=native.task_record(settings,state['author_task'],config['author'])
        revised=prepare_decomposition(config,state,task,native.task_messages(settings,task['id']),fx.remaining_calls())
        labels=b.docker('GET','/volumes/'+state['snapshot']['volume'])['Labels']
        if labels.get('delivery-kit.owner')!=b.OWNER or labels.get('delivery-kit.source-task')!=task['id']:
            raise ValueError('owned current immutable decomposition source required')
        evidence=revised['c10_decomposition']['c09_evidence'];failure=evidence['full_suite_failure']
        output=con.execute('SELECT output FROM frozen_suite_failures WHERE task_id=? AND output_sha256=?',
            (evidence['task_id'],failure['output_sha256'])).fetchone()
        if not output or hashlib.sha256(output[0].encode()).hexdigest()!=failure['output_sha256']:
            raise ValueError('durable actual C09 progress required')
        con.execute('UPDATE harness_repair_tasks SET state=? WHERE source_task=?',(json.dumps(revised,sort_keys=True),source))
    return {'stage':revised['stage'],'attempt_limit':1,'author_scope_authorized':False,'delivery_approval':False}


def prepare_decomposition_feedback(state):
    plan=state.get('c10_decomposition',{});report=state.get('functional_diagnosis_receipt',{})
    reason=report.get('decision',{}).get('reason','')
    if (plan.get('plan_feedback') or plan.get('author_scope_authorized') is not False
            or state.get('stage')!='blocked' or state.get('category')!='maintenance_diagnosis_driver_observation'
            or report.get('classification')!='DRIVER_OBSERVATION'
            or report.get('certificate',{}).get('snapshot')!=state['snapshot']['volume']
            or report.get('certificate',{}).get('test_sha256')!=state['validation']['test_sha256']
            or 'app.js lines 512/515/528/531' not in reason):
        raise ValueError('exact unconsumed source-path contradiction required')
    note=('CTO READONLY C10 PLAN CORRECTION. Read all four mounted files fully. '
        'Your prior plan is NOT approved: it assigns QUERY edits to app.js lines '
        '512/515/528/531. Those bare-array response lines belong to '
        'tests/test_incremental_u3.py DRIVER_BODY, NOT app.js. Product code is '
        'immutable. Correct the file/path and give a concise complete TWO-checkpoint '
        'plan. QUERY: only wrap the four existing response arrays in that TEST file '
        'as {items:[...]}; no promise-flow, fixture, C09 or C10STATUS changes. '
        'Acceptance must prove actual gamma rendering, stale-query rejection and '
        'C09 preservation on frozen output. Full259-test execution is required; '
        'unimplemented status fields may cause the sole C10 status-stage failure '
        '(status_genA_urls); identify that expected PARTIAL outcome explicitly. '
        'No other failure is allowed; partial is not Green or approval. '
        'STATUS: separately replace only the placeholder using actual open/completed '
        'filter actions, URLs, valid current/stale response envelopes and late '
        'pending_left; choose exact balanced original closure boundaries. This '
        'stage requires all259 tests Green on its own frozen SHA, then independent '
        'maintenance review. Preserve every test and preamble, product and C09. '
        'Only original TEST driver lines500-553; max4 ranges,4096bytes each, '
        '32768bytes final. Immutable reads only: no edits, terminal, approval, '
        'budget/model change or CEO technical questions. Reason target650chars, '
        'max900, request_test_revision DRIVER_OBSERVATION: with QUERY and STATUS, '
        'correct TEST path and gates; optional_files=[]. Otherwise UNRESOLVED: '
        'escalate_cto. No author authorized.\n'
        'DELIVERY_CURRENT_HARNESS_DIAGNOSIS_V1\nDELIVERY_STRUCTURED_DECISION_V1:technical\n'
        'DELIVERY_TYPED_DECISION_V1\nDELIVERY_TECHNICAL_LENGTH_FEEDBACK_V1\n'
        'DELIVERY_DETERMINISTIC_READ_V1\n'+
        ''.join('DELIVERY_REVIEW_READ_PATH:'+p+'\n' for p in delivery.paths()))
    revised=copy.deepcopy(state)
    revised['c10_decomposition']['plan_feedback']={'prior_receipt':revised.pop('functional_diagnosis_receipt'),
        'prior_diagnosis':revised['functional_diagnosis'],'source_path_verified':False,
        'attempt_limit':1,'delivery_approval':False,'at':time.time()}
    revised['functional_diagnosis']=dict(revised['functional_diagnosis'],note=note,at=time.time())
    revised.update(stage='maintenance_functional_diagnosis_dispatch',category='c10_decomposition_path_feedback',delivery_approval=False)
    return revised


def register_decomposition_feedback(b,source):
    with b.LOCK,b.db() as con:
        config,state=map(json.loads,con.execute('SELECT config,state FROM harness_repair_tasks WHERE source_task=?',(source,)).fetchone())
        admission_controls_spike.verify_current(con,config)
        if state.get('c10_decomposition',{}).get('plan_feedback'):return {'stage':state['stage'],'reused':True,'author_scope_authorized':False}
        if con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone():raise ValueError('idle feedback required')
        settings=json.loads((b.STATE/'native.json').read_text());fx=handoff_runtime.Effects(b,settings)
        if fx.remaining_calls()<56 or any(t.get('status') in ('queued','dispatched','running') for t in native.issue_task_runs(settings,state['issue_id'])):
            raise ValueError('idle diagnosis and author/review reserve required')
        report=state['functional_diagnosis_receipt'];task=native.task_record(settings,report['certificate']['task_id'],config['cto'])
        try:import harness_repair_task as h
        except ImportError:from broker import harness_repair_task as h
        if h.qualify_diagnosis(config,state,task,fx.decision(task),fx.read_evidence(task))!=report['certificate']:
            raise ValueError('actual current full-read CTO evidence required')
        revised=prepare_decomposition_feedback(state)
        con.execute('UPDATE harness_repair_tasks SET state=? WHERE source_task=?',(json.dumps(revised,sort_keys=True),source))
    return {'stage':revised['stage'],'author_scope_authorized':False,'delivery_approval':False}


def prepare_classification_feedback(state,task,decision,certificate):
    plan=state.get('c10_decomposition',{})
    if (plan.get('classification_feedback') or not plan.get('plan_feedback')
            or state.get('stage')!='blocked' or state.get('category')!='invalid_or_unread_driver_diagnosis'
            or plan.get('author_scope_authorized') is not False or state.get('functional_diagnosis_receipt')
            or certificate.get('task_id')!=task.get('id') or certificate.get('snapshot')!=state['snapshot']['volume']
            or certificate.get('test_sha256')!=state['validation']['test_sha256']
            or decision.get('action')!='request_test_revision' or decision.get('optional_files')!=[]
            or not isinstance(decision.get('reason'),str) or not 0<len(decision['reason'])<=1200
            or decision['reason'].split(':',1)[0] in ('DRIVER_OBSERVATION','PRODUCT_REGRESSION','UNRESOLVED')
            or 'tests/test_incremental_u3.py' not in decision['reason']
            or any(term not in decision['reason'] for term in ('QUERY','STATUS','259','PARTIAL'))):
        raise ValueError('exact fully-read plan with missing classification required')
    revised=copy.deepcopy(state)
    revised['c10_decomposition']['classification_feedback']={'task_id':task['id'],
        'actual_decision':decision,'certificate':certificate,'prior_diagnosis':state['functional_diagnosis'],
        'reason':'missing_explicit_classification','attempt_limit':1,'delivery_approval':False,'at':time.time()}
    note=('CTO READONLY CLASSIFIED C10 PLAN. Read all four files completely. '
        'Your preceding QUERY/STATUS plan corrected the TEST path but was rejected '
        'because reason did NOT begin with DRIVER_OBSERVATION:. No local relabeling '
        'was applied; that decision is preserved as invalid, not authority. '
        'Return a fresh structured decision. For a supported driver-only plan, '
        'action=request_test_revision, optional_files=[], and reason MUST START '
        'EXACTLY with "DRIVER_OBSERVATION: ", then concise QUERY and STATUS scopes '
        'and gates. No introduction before that literal prefix. If unsupported, '
        'action=escalate_cto with reason starting "UNRESOLVED: ". '
        'QUERY: only items envelopes at TEST FILE tests/test_incremental_u3.py '
        '512/515/528/531; no product, promise, fixture, C09 or status change. '
        'Prove gamma rendering, stale rejection and C09 preservation; full259-test '
        'run may have ONLY the pending C10 status_genA_urls error. Explicit PARTIAL '
        'checkpoint, not Green or approval. STATUS: separately fill534-536 with '
        'real filter-open/completed events, issued URLs, valid current/stale '
        'response envelopes and final pending_left, preserving original closures. '
        'All259 tests must pass on exact frozen output, then independent review. '
        'Preserve all assertions and preamble. Driver scope500-553,4 V4 ranges, '
        '4096bytes each,32768bytes final. Reason max900chars, target650, complete '
        'prose. No author authorized, edits, terminal, approvals, administrative '
        'actions, model/cap changes or CEO technical questions.\n'
        'DELIVERY_CURRENT_HARNESS_DIAGNOSIS_V1\nDELIVERY_STRUCTURED_DECISION_V1:technical\n'
        'DELIVERY_TYPED_DECISION_V1\nDELIVERY_TECHNICAL_LENGTH_FEEDBACK_V1\n'
        'DELIVERY_DETERMINISTIC_READ_V1\n'+
        ''.join('DELIVERY_REVIEW_READ_PATH:'+p+'\n' for p in delivery.paths()))
    revised['functional_diagnosis']=dict(state['functional_diagnosis'],note=note,at=time.time())
    revised.update(stage='maintenance_functional_diagnosis_dispatch',category='c10_decomposition_classification_feedback',delivery_approval=False)
    return revised


def register_classification_feedback(b,source):
    with b.LOCK,b.db() as con:
        config,state=map(json.loads,con.execute('SELECT config,state FROM harness_repair_tasks WHERE source_task=?',(source,)).fetchone())
        admission_controls_spike.verify_current(con,config)
        if state.get('c10_decomposition',{}).get('classification_feedback'):return {'stage':state['stage'],'reused':True,'author_scope_authorized':False}
        if con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone():raise ValueError('idle classified diagnosis required')
        settings=json.loads((b.STATE/'native.json').read_text());fx=handoff_runtime.Effects(b,settings)
        if fx.remaining_calls()<56 or any(t.get('status') in ('queued','dispatched','running') for t in native.issue_task_runs(settings,state['issue_id'])):
            raise ValueError('idle classification and author/review reserve required')
        tasks=[t for t in native.issue_task_runs(settings,state['issue_id']) if t.get('wakeup_id')==state['diagnosis']['wakeup_id'] and t.get('agent_id')==config['cto']]
        if len(tasks)!=1:raise ValueError('exact current CTO task required')
        task=tasks[0];decision=fx.decision(task)
        try:import harness_repair_task as h
        except ImportError:from broker import harness_repair_task as h
        certificate=h.qualify_diagnosis(config,state,task,decision,fx.read_evidence(task))
        revised=prepare_classification_feedback(state,task,decision,certificate)
        con.execute('UPDATE harness_repair_tasks SET state=? WHERE source_task=?',(json.dumps(revised,sort_keys=True),source))
    return {'stage':revised['stage'],'author_scope_authorized':False,'delivery_approval':False}


def register(b,source,proof):
    with b.LOCK,b.db() as con:
        config,state=map(json.loads,con.execute('SELECT config,state FROM harness_repair_tasks WHERE source_task=?',(source,)).fetchone())
        admission_controls_spike.verify_current(con,config)
        if state.get('c10_syntax_recovery'):
            if state['c10_syntax_recovery']['qualification']!=proof:raise ValueError('C10 recovery qualification drift')
            return {'stage':state['stage'],'reused':True,'delivery_approval':False}
        if con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone():raise ValueError('idle recovery required')
        settings=json.loads((b.STATE/'native.json').read_text());fx=handoff_runtime.Effects(b,settings)
        if any(t.get('status') in ('queued','dispatched','running') for t in native.issue_task_runs(settings,state['issue_id'])):
            raise ValueError('idle native maintenance required')
        task=native.task_record(settings,state['author_task'],config['author'])
        report=state['functional_diagnosis_receipt'];cert=report['certificate']
        cto=native.task_record(settings,cert['task_id'],config['cto']);decision=fx.decision(cto)
        try:import harness_repair_task as h
        except ImportError:from broker import harness_repair_task as h
        diagnosed=dict(state,snapshot=state['functional_diagnosis']['snapshot'],validation=state['functional_diagnosis']['validation'])
        actual_cert=h.qualify_diagnosis(config,diagnosed,cto,decision,fx.read_evidence(cto))
        if delivery.qualify_functional_decision(diagnosed,decision,actual_cert)!=report:
            raise ValueError('actual current independent CTO certificate drift')
        revised,seed=prepare(config,state,task,native.task_messages(settings,task['id']),proof,fx.remaining_calls())
        for item in (seed,{'task_id':task['id'],'snapshot':state['snapshot']}):
            labels=b.docker('GET','/volumes/'+item['snapshot']['volume'])['Labels']
            if labels.get('delivery-kit.owner')!=b.OWNER or labels.get('delivery-kit.source-task')!=item['task_id']:
                raise ValueError('exact frozen snapshot ownership required')
        if b.docker('GET','/images/'+proof['worker_image']+'/json')['Id']!=proof['worker_image']:
            raise ValueError('qualified recovery worker missing')
        suite=con.execute('SELECT status FROM maintenance_suite_runs WHERE task_id=?',(seed['task_id'],)).fetchone()
        failure=con.execute('SELECT output FROM frozen_suite_failures WHERE task_id=? AND output_sha256=?',
            (seed['task_id'],revised['c10_diagnosis']['c09_evidence']['full_suite_failure']['output_sha256'])).fetchone()
        if not suite or suite[0]!='failed' or not failure or hashlib.sha256(failure[0].encode()).hexdigest()!=revised['c10_diagnosis']['c09_evidence']['full_suite_failure']['output_sha256']:
            raise ValueError('durable C09 progress receipt required')
        try:import driver_checkpoint_policy as policy
        except ImportError:from broker import driver_checkpoint_policy as policy
        grant=policy.select(config,dict(revised,stage='awaiting_author'),revised['issue_id'],
            {'id':'recovery-admission','issue_id':revised['issue_id'],'agent_id':config['author'],'wakeup_id':revised['wakeup_id']})
        if grant['worker_image']!=proof['worker_image']:raise ValueError('scoped recovery worker selection drift')
        trial=json.loads(con.execute('SELECT config FROM test_revision_trials WHERE issue_id=?',(state['issue_id'],)).fetchone()[0])
        if trial.get('harness_maintenance_only') is not True:raise ValueError('maintenance-only recovery required')
        trial['maintenance_seed']={'source':source,'receipt':seed}
        con.execute('UPDATE test_revision_trials SET config=? WHERE issue_id=?',(json.dumps(trial,sort_keys=True),state['issue_id']))
        con.execute('UPDATE harness_repair_tasks SET state=? WHERE source_task=?',(json.dumps(revised,sort_keys=True),source))
    return {'stage':revised['stage'],'scope_id':revised['c10_syntax_recovery']['scope_id'],
        'attempt_limit':1,'delivery_approval':False}
