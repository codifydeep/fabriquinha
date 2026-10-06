"""One isolated, CTO-sponsored fixture-maintenance task; never release retry."""
import hashlib,inspect,json,time,re
try:
    import native,handoff_runtime,harness_prerequisite,admission_controls_spike
    from incremental_provisioning import NativeIssues
except ImportError:
    from broker import native,handoff_runtime,harness_prerequisite,admission_controls_spike
    from broker.incremental_provisioning import NativeIssues


def author_note(config, decision):
    return ('ISOLATED HARNESS MAINTENANCE, NOT PRODUCT IMPLEMENTATION OR FUNCTIONAL RED. '
        'Repair only /workspace/tests/test_incremental_u3.py seeded from the rejected frozen '
        'candidate. Preserve every existing method and assertion. Do not implement product, '
        'remove C10, introduce skips, weaken assertions, change discovery or fabricate report '
        'values. Fix the driver prerequisite only; new negative controls are a later task. '
        'Perform real edits only; the controller executes the complete pinned suite on the frozen submission. '
        'The controller will perform Python compile and Node --check offline; do not request '
        'those commands or a generic shell from worker tools. '
        'Explain any remaining functional assertion failures; syntax/import/missing-report-key '
        'errors are not acceptable. Do not label a syntax fix as functional Red or delivery. '
        'CTO repair scope: '+decision['reason'])


def initialize(con):
    con.execute('CREATE TABLE IF NOT EXISTS harness_repair_tasks(source_task TEXT PRIMARY KEY,config TEXT,state TEXT)')


def inspection():
    """Fixed offline inspection; no agent command or fabricated Red."""
    import ast,hashlib,json,subprocess
    from pathlib import Path
    name='tests/test_incremental_u3.py'
    old=Path('/previous')/name;new=Path('/candidate')/name
    raw=new.read_bytes();facts={'bytes':len(raw),'test_sha256':hashlib.sha256(raw).hexdigest(),
        'source_changed':raw!=old.read_bytes(),'functional_red':False,'delivery_approval':False}
    encoded=(new.parent.parent/'manifest.json').read_bytes()
    manifest=json.loads(encoded)['files']
    if manifest[name]!={'sha256':facts['test_sha256'],'bytes':len(raw)}:
        raise ValueError('frozen manifest mismatch')
    facts['manifest_sha256']=hashlib.sha256(encoded).hexdigest()
    trees=[]
    try:
        trees=[ast.parse(p.read_bytes()) for p in (old,new)]
        facts['python_syntax_valid']=True
    except SyntaxError:
        facts['python_syntax_valid']=False;print(json.dumps(facts));return
    def methods(t):
        return {n.name:ast.dump(n,include_attributes=False) for n in ast.walk(t)
            if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}
    facts['test_methods_preserved']=methods(trees[0])==methods(trees[1])
    for tree in trees:
        drivers=[n for n in tree.body if isinstance(n,ast.Assign)
            and any(isinstance(x,ast.Name) and x.id=='DRIVER_BODY' for x in n.targets)]
        if len(drivers)!=1:raise ValueError('single driver required')
        driver=ast.literal_eval(drivers[0].value)
        drivers[0].value=ast.Constant(value='DRIVER_ONLY')
    facts['non_driver_ast_preserved']=ast.dump(trees[0],include_attributes=False)==ast.dump(trees[1],include_attributes=False)
    facts['node_syntax_valid']=subprocess.run(['node','--check'],input=driver,text=True,
        capture_output=True,timeout=10).returncode==0
    print(json.dumps(facts))


def classification(facts):
    if not facts.get('source_changed'):return 'unchanged_invalid_driver'
    if facts.get('python_syntax_valid') is not True:return 'python_syntax_error'
    if facts.get('node_syntax_valid') is not True:return 'driver_syntax_error'
    if facts.get('test_methods_preserved') is not True:return 'test_methods_changed'
    if facts.get('non_driver_ast_preserved') is not True:return 'outside_driver_scope_changed'
    return 'independent_review_required'


def checkpoint_note(number, decision):
    if number not in (1,2):raise ValueError('invalid maintenance checkpoint')
    scope=('CHECKPOINT1 SYNTAX ONLY. Seed is the original frozen test, NOT the previous '
        'failed broad rewrite. Close only the broken DRIVER_BODY promise constructs. '
        'Do NOT implement C10 yet. Keep DRIVER_PREAMBLE and all other Python AST unchanged. '
        'Submit after the minimal edit; controller Python/Node checks gate checkpoint2. '
        'Do not call a compiler, Python tool or generic shell; do not claim checks executed.'
        if number==1 else
        'CHECKPOINT2 C10 ONLY. Seed is the controller-validated syntax checkpoint. '
        'Populate status_genA_urls/status_genB_urls/rendered_after_current_status from real '
        'open/completed requests, resolveNewest current then resolveOldest stale. Keep the '
        'balanced syntax and all non-driver Python AST. Submit the real edit; the controller '
        'executes the complete pinned suite on the frozen snapshot. Do not request terminal '
        'or claim that you executed tests. Functional failures and harness errors are recorded separately.')
    return (scope+' Final file<=32768UTF-8bytes. Preserve every test method and assertion; '
        'no skips, fabricated constants, product edits, discovery changes, Red or delivery '
        'approval. Do not repeat a rejected patch. CTO scope: '+decision['reason'])


def start_staged(b,source):
    with b.LOCK,b.db() as con:
        config,state=map(json.loads,con.execute('SELECT config,state FROM harness_repair_tasks WHERE source_task=?',(source,)).fetchone())
        admission_controls_spike.verify_current(con,config)
        if state.get('staged'):return {'stage':state['stage'],'reused':True}
        if state.get('stage')!='diagnosis_complete':raise ValueError('qualified diagnosis required')
        settings=json.loads((b.STATE/'native.json').read_text());fx=handoff_runtime.Effects(b,settings)
        task=native.task_record(settings,state['diagnosis_certificate']['task_id'],config['cto'])
        decision=fx.decision(task)
        proof=qualify_diagnosis(config,state,task,decision,fx.read_evidence(task))
        if decision!=state['diagnosis_decision'] or proof!=state['diagnosis_certificate'] or decision['action']!='request_test_revision':
            raise ValueError('diagnosis drift')
        if con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone():raise ValueError('idle required')
        if fx.remaining_calls()<60:raise ValueError('two checkpoints plus review reserve required')
        state['staged']={'current':1,'history':[],'cto_task':task['id'],'prior_rejected_task':state['author_task']}
        state.update(stage='checkpoint_dispatch_intent',at=time.time())
        con.execute('UPDATE harness_repair_tasks SET state=? WHERE source_task=?',(json.dumps(state,sort_keys=True),source))
    dispatch_checkpoint(b,source)
    return {'stage':'checkpoint_dispatched','checkpoint':1,'delivery_approval':False}


def dispatch_checkpoint(b,source):
    with b.LOCK,b.db() as con:
        config,state=map(json.loads,con.execute('SELECT config,state FROM harness_repair_tasks WHERE source_task=?',(source,)).fetchone())
        admission_controls_spike.verify_current(con,config)
        if state['stage']!='checkpoint_dispatch_intent':return
        number=state['staged']['current']
        if state.get('c10_checkpoints'):
            try:import c10_checkpoint_contract as gates
            except ImportError:from broker import c10_checkpoint_contract as gates
            note=gates.admission(state).author_note(state)
            origin=state['c10_checkpoints']['authority']['certificate']['task_id']
        else:
            note=checkpoint_note(number,state['diagnosis_decision'])
            if state.get('functional_correction'):
                try:import maintenance_delivery
                except ImportError:from broker import maintenance_delivery
                note=maintenance_delivery.functional_correction_note(state)
            elif state['staged'].get('driver_guard'):note+='\nDELIVERY_DRIVER_CHECKPOINT_V3'
            origin=state['staged'].get('driver_guard',{}).get('origin_task',state['staged']['cto_task']) if number==1 else state['staged']['history'][0]['task_id']
            if state.get('functional_correction'):origin=state['functional_correction']['cto_task']
            if state.get('functional_fragment_recovery'):
                recovery=state['functional_fragment_recovery']
                origin=recovery['failed_task'] if recovery['current']==1 else recovery['history'][0]['seed']['task_id']
        marker=hashlib.sha256((source+':checkpoint:'+str(number)+':'+origin+':'+note).encode()).hexdigest()
        settings=json.loads((b.STATE/'native.json').read_text());fx=handoff_runtime.Effects(b,settings)
        try:
            wake=native.ensure_unit_start(settings,state['issue_id'],config['author'],origin,marker,note,allow_create=fx.remaining_calls()>=40)
        except Exception as error:
            state.update(stage='blocked',category='maintenance_dispatch_identity_failed' if isinstance(error,ValueError) else 'maintenance_dispatch_infrastructure_failed',
                owner=config['cto'],dispatch_error_type=type(error).__name__,dispatch_marker=marker,at=time.time())
            con.execute('UPDATE harness_repair_tasks SET state=? WHERE source_task=?',(json.dumps(state,sort_keys=True),source))
            return
        if not wake:
            state.update(stage='blocked',category='maintenance_author_budget_required',owner=config['cto'],at=time.time())
            con.execute('UPDATE harness_repair_tasks SET state=? WHERE source_task=?',(json.dumps(state,sort_keys=True),source))
            return
        state.update(stage='awaiting_author',wakeup_id=wake['id'],at=time.time())
        con.execute('UPDATE harness_repair_tasks SET state=? WHERE source_task=?',(json.dumps(state,sort_keys=True),source))


def checkpoint_passed(facts):
    return (classification(facts)=='independent_review_required' and type(facts.get('bytes')) is int
        and 0<facts['bytes']<=32768 and isinstance(facts.get('manifest_sha256'),str) and len(facts['manifest_sha256'])==64)


def arm_driver_guard(b,source,qualification):
    """One changed-contract restart; exact CTO authority and failed attempt retained."""
    try:import driver_checkpoint_policy
    except ImportError:from broker import driver_checkpoint_policy
    with b.LOCK,b.db() as con:
        config,state=map(json.loads,con.execute('SELECT config,state FROM harness_repair_tasks WHERE source_task=?',(source,)).fetchone())
        admission_controls_spike.verify_current(con,config)
        staged=state.get('staged',{})
        if staged.get('driver_guard'):
            if staged['driver_guard']['qualification']!=qualification:raise ValueError('driver guard already consumed')
            return {'stage':state['stage'],'reused':True,'delivery_approval':False}
        if state.get('stage')!='blocked' or state.get('category')!='driver_syntax_error' or staged.get('current')!=1 or staged.get('history'):
            raise ValueError('exact failed syntax checkpoint required')
        if con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone():raise ValueError('idle guard registration required')
        settings=json.loads((b.STATE/'native.json').read_text());fx=handoff_runtime.Effects(b,settings)
        if fx.remaining_calls()<60:raise ValueError('author checkpoints and independent review reserve required')
        old=native.task_record(settings,state['author_task'],config['author'])
        if old.get('status')!='completed' or old.get('issue_id')!=state['issue_id'] or old.get('wakeup_id')!=state['wakeup_id']:
            raise ValueError('exact completed failed checkpoint required')
        if any(r.get('status') in ('queued','dispatched','running') for r in native.issue_task_runs(settings,state['issue_id'])):
            raise ValueError('idle native maintenance required')
        cert=state['diagnosis_certificate']
        diagnostic_state={**state,'snapshot':{'volume':cert['snapshot']},'validation':{'test_sha256':cert['test_sha256']}}
        cto=native.task_record(settings,cert['task_id'],config['cto']);decision=fx.decision(cto)
        if decision!=state['diagnosis_decision'] or qualify_diagnosis(config,diagnostic_state,cto,decision,fx.read_evidence(cto))!=cert:
            raise ValueError('original independent diagnosis drift')
        guard={'qualification':qualification,'worker_image':qualification['worker_image'],
            'origin_task':state['author_task'],'failed_attempt':{k:state[k] for k in
                ('author_task','wakeup_id','snapshot','validation','category')},'attempt_limit':1}
        candidate=json.loads(json.dumps(state));candidate['staged']['driver_guard']=guard
        candidate['stage']='awaiting_author'
        selected=driver_checkpoint_policy.select(config,candidate,state['issue_id'],
            {'id':'qualification-only','issue_id':state['issue_id'],'agent_id':config['author'],'wakeup_id':state['wakeup_id']})
        image=b.docker('GET','/images/'+selected['worker_image']+'/json')
        if not image or image.get('Id')!=selected['worker_image']:raise ValueError('exact qualified worker image absent')
        state['staged']['driver_guard']=guard
        state.update(stage='checkpoint_dispatch_intent',category='driver_guarded_checkpoint1_pending',at=time.time())
        con.execute('UPDATE harness_repair_tasks SET state=? WHERE source_task=?',(json.dumps(state,sort_keys=True),source))
    return {'stage':'checkpoint_dispatch_intent','protocol':'typed_driver_v3','delivery_approval':False}


def diagnosis_note(state):
    return ('CTO: diagnose the failed isolated driver repair, NOT product delivery. '
        'Read all mounted candidate files and the previous test. Candidate Python parses '
        'but DRIVER_BODY fails node --check (missing closing parenthesis at driver line165). '
        'All test methods and31assertions were preserved, but non-driver Python AST changed. '
        'Repeated patches hit the32768-byte final-write fence. Candidate32642bytes; do not '
        'increase caps, remove tests, fabricate observations or send technical questions to CEO. '
        'Identify exact unbalanced constructs and changes outside DRIVER_BODY. Recommend a '
        'different, bounded repair strategy with objective syntax/harness acceptance, ideally '
        'smaller staged edits rather than another broad rewrite. You cannot edit or execute tools '
        'other than immutable reads. Return action=request_test_revision with concrete scope '
        'and staged checkpoints in reason(max1200characters), or escalate_cto if unresolved; '
        'optional_files=[]. No permission, implementation, Red or delivery approval.\n'
        'DELIVERY_STRUCTURED_DECISION_V1:technical\nDELIVERY_TYPED_DECISION_V1\n'
        'DELIVERY_DETERMINISTIC_READ_V1\n'+''.join('DELIVERY_REVIEW_READ_PATH:'+p+'\n' for p in diagnosis_paths()))


def diagnosis_paths():
    return ['/evidence/candidate/'+p for p in ('app/static/app.js','app/static/index.html','tests/test_incremental_u3.py')]+[
        '/evidence/previous/tests/test_incremental_u3.py']


def rejected_driver_operations(messages):
    """Only observed native tool results; no inferred executions or proposal text."""
    calls={m['call_id'] for m in messages if m.get('type')=='tool_use' and m.get('tool')=='surgical_test_edit'}
    results=[]
    for message in messages:
        if message.get('type')!='tool_result' or message.get('call_id') not in calls:continue
        output=message.get('output')
        if not isinstance(output,str) or message.get('output_truncated'):raise ValueError('complete surgical rejection result required')
        categories=re.findall(r'surgical_edit_rejected:([a-z_]+):',output)
        if len(categories)!=1 or categories[0] not in ('no_bounded_change','driver_syntax_invalid'):
            raise ValueError('exact measured bounded driver rejection required')
        results.append({'call_id':message['call_id'],'category':categories[0],
            'output_sha256':hashlib.sha256(output.encode()).hexdigest()})
    if len(calls)!=2 or len(results)!=2 or len({r['call_id'] for r in results})!=2 or {r['category'] for r in results}!={'no_bounded_change','driver_syntax_invalid'}:
        raise ValueError('two distinct measured driver rejections required')
    return results


def rejection_diagnosis_note(state,operations):
    return ('CTO: diagnose two actual bounded DRIVER_BODY repair rejections. This is '
        'ISOLATED HARNESS MAINTENANCE, not product delivery. Read every mounted candidate '
        'file and original test fully. Candidate is unchanged: Python valid, Node invalid, '
        'all test methods/assertions and non-driver Python AST preserved. Rejections: '+
        ', '.join(r['category'] for r in operations)+'. The proxy previously supplied wrong '
        'scaffolding-adaptation instructions; that text is now corrected to DRIVER_BODY only. '
        'The first proposed edit made no bounded change; second did not produce valid JS. '
        'Identify the exact unclosed constructs in the original literal DRIVER_BODY, give '
        'precise source anchors/closure order and a genuinely different bounded syntax-only '
        'repair strategy. Do NOT implement C10 yet. Author can submit at most4unique changed '
        'old/new fragments, each<=4096UTF-8bytes; full file<=32768bytes. Handler validates '
        'entire non-driver AST and fixed Node syntax before writing. No imports/preamble/test '
        'body edits, no weaker tests, larger caps, terminal, patches, fabricated observations '
        'or questions to CEO. Controller runs full suite after checkpoint2 and requests '
        'independent review. You have immutable reads only. Return request_test_revision '
        'with exact diagnosis and changed repair strategy in reason(max1200chars), or '
        'escalate_cto if no safe bounded repair is available; optional_files=[]. No approval '
        'of implementation, Red, merge or delivery.\nDELIVERY_STRUCTURED_DECISION_V1:technical\n'
        'DELIVERY_TYPED_DECISION_V1\nDELIVERY_DETERMINISTIC_READ_V1\n'+
        ''.join('DELIVERY_REVIEW_READ_PATH:'+p+'\n' for p in diagnosis_paths()))


def diagnose_rejected_driver(b,source):
    with b.LOCK,b.db() as con:
        config,state=map(json.loads,con.execute('SELECT config,state FROM harness_repair_tasks WHERE source_task=?',(source,)).fetchone())
        admission_controls_spike.verify_current(con,config)
        if state.get('rejection_replan'):return {'stage':state['stage'],'reused':True}
        if state.get('stage')!='blocked' or state.get('category')!='unchanged_invalid_driver' or not state.get('staged',{}).get('driver_guard'):
            raise ValueError('exact blocked V3 author required')
        if con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone():raise ValueError('idle diagnosis required')
        settings=json.loads((b.STATE/'native.json').read_text());fx=handoff_runtime.Effects(b,settings)
        task=native.task_record(settings,state['author_task'],config['author'])
        if task.get('status')!='completed' or task.get('issue_id')!=state['issue_id'] or task.get('wakeup_id')!=state['wakeup_id']:raise ValueError('exact completed rejected author required')
        if any(t.get('status') in ('queued','dispatched','running') for t in native.issue_task_runs(settings,state['issue_id'])):raise ValueError('idle native diagnosis required')
        facts=state['validation']
        if facts['source_changed'] is not False or facts['test_sha256']!=config['file_sha256']['tests/test_incremental_u3.py'] or facts['node_syntax_valid'] is not False:
            raise ValueError('original unchanged invalid driver required')
        labels=b.docker('GET','/volumes/'+state['snapshot']['volume'])['Labels']
        if labels.get('delivery-kit.owner')!=b.OWNER or labels.get('delivery-kit.source-task')!=task['id']:raise ValueError('exact frozen rejected source required')
        operations=rejected_driver_operations(native.task_messages(settings,task['id']))
        if fx.remaining_calls()<8:raise ValueError('diagnosis reserve required')
        note=rejection_diagnosis_note(state,operations)
        state['rejection_replan']={'author_task':task['id'],'snapshot':state['snapshot'],'validation':facts,
            'operations':operations,'note':note,'prior_diagnosis':{k:state.get(k) for k in
                ('diagnosis','diagnosis_certificate','diagnosis_decision')},'attempt_limit':1,'at':time.time()}
        state.update(stage='rejection_diagnosis_dispatch',category='cto_driver_rejection_diagnosis',owner=config['cto'],at=time.time())
        con.execute('UPDATE harness_repair_tasks SET state=? WHERE source_task=?',(json.dumps(state,sort_keys=True),source))
    return {'stage':'rejection_diagnosis_dispatch','delivery_approval':False}


def prepare_diagnosis_format_recovery(config,state,task,reads,event,execution):
    """One changed-format submission; never accept/truncate rejected arguments."""
    if (state.get('stage')!='blocked' or state.get('category')!='invalid_or_unread_driver_diagnosis'
            or not state.get('rejection_replan') or state.get('diagnosis_format_recovery')
            or task.get('status')!='failed' or task.get('agent_id')!=config['cto']
            or task.get('issue_id')!=state['issue_id']
            or task.get('wakeup_id')!=state['diagnosis']['wakeup_id']
            or event.get('execution_id')!=execution or event.get('status')!=502
            or event.get('category')!='structured_decision_response_invalid'
            or event.get('structured_rejection_category')!='typed_schema_maxLength'
            or event.get('decision_rejection_persisted') is not True
            or type(event.get('call_number')) is not int
            or not re.fullmatch('[a-f0-9]{64}',event.get('decision_upstream_sha256',''))):
        raise ValueError('exact one-shot format rejection required')
    if any(type(reads.get(p,{}).get('lines')) is not int or reads[p]['lines']<=0
            or reads[p]['lines']!=reads[p].get('total_lines') for p in diagnosis_paths()):
        raise ValueError('full actual frozen reads required')
    note=state['rejection_replan']['note']
    note=note.replace('with exact diagnosis and changed repair strategy in reason(max1200chars)',
        'with ONE concise sentence in reason: target at most600characters, hard limit1200. '
        'Name the source anchor, closure order and changed strategy only; omit background, '
        'policy recitation, file contents and narration')
    if note==state['rejection_replan']['note']:raise ValueError('changed format instruction required')
    state['diagnosis_format_recovery']={'failed_task':task['id'],'execution_id':execution,
        'prior_diagnosis':state['diagnosis'],'event':event,'reads':reads,
        'attempt_limit':1,'at':time.time(),'delivery_approval':False}
    state['rejection_replan']['note']=note
    state.update(stage='rejection_diagnosis_dispatch',category='cto_diagnosis_format_recovery',at=time.time())
    return state


def recover_diagnosis_format(b,source):
    """Operator admission after exact transport evidence, idle and snapshot checks."""
    with b.LOCK,b.db() as con:
        config,state=map(json.loads,con.execute('SELECT config,state FROM harness_repair_tasks WHERE source_task=?',(source,)).fetchone())
        admission_controls_spike.verify_current(con,config)
        if state.get('diagnosis_format_recovery'):return {'stage':state['stage'],'reused':True}
        if con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone():raise ValueError('idle format recovery required')
        settings=json.loads((b.STATE/'native.json').read_text());fx=handoff_runtime.Effects(b,settings)
        runs=native.issue_task_runs(settings,state['issue_id'])
        if any(t.get('status') in ('queued','dispatched','running') for t in runs):raise ValueError('idle native recovery required')
        failed=[t for t in runs if t.get('wakeup_id')==state['diagnosis']['wakeup_id'] and t.get('agent_id')==config['cto']]
        if len(failed)!=1:raise ValueError('unique failed CTO task required')
        task=native.task_record(settings,failed[0]['id'],config['cto'])
        bindings=con.execute('SELECT request_id FROM native_bindings WHERE task_id=?',(task['id'],)).fetchall()
        if len(bindings)!=1:raise ValueError('unique native execution binding required')
        execution=bindings[0][0];events=[]
        for line in b.docker_stdout(b.PREFIX+'-model-proxy-1',limit=262144).splitlines():
            try:event=json.loads(line)
            except ValueError:continue
            if event.get('execution_id')==execution and event.get('call_number') is not None:events.append(event)
        if len(events)!=1:raise ValueError('one measured upstream decision required')
        labels=b.docker('GET','/volumes/'+state['snapshot']['volume'])['Labels']
        if labels.get('delivery-kit.owner')!=b.OWNER or labels.get('delivery-kit.source-task')!=state['author_task']:raise ValueError('frozen author identity required')
        if fx.remaining_calls()<68:raise ValueError('diagnosis plus author and review reserve required')
        state=prepare_diagnosis_format_recovery(config,state,task,fx.read_evidence(task),events[0],execution)
        con.execute('UPDATE harness_repair_tasks SET state=? WHERE source_task=?',(json.dumps(state,sort_keys=True),source))
    return {'stage':state['stage'],'delivery_approval':False,'attempt_limit':1}


def dispatch_rejection_diagnosis(b,source):
    with b.LOCK,b.db() as con:
        config,state=map(json.loads,con.execute('SELECT config,state FROM harness_repair_tasks WHERE source_task=?',(source,)).fetchone())
        admission_controls_spike.verify_current(con,config)
        if state['stage']!='rejection_diagnosis_dispatch':return
        plan=state['rejection_replan'];note=plan['note']
        marker=hashlib.sha256((plan['author_task']+':bounded-driver-rejection-diagnosis:'+note).encode()).hexdigest()
        settings=json.loads((b.STATE/'native.json').read_text());fx=handoff_runtime.Effects(b,settings)
        try:
            wake=fx.ensure_wakeup(state['issue_id'],config['cto'],plan['author_task'],marker,note,allow_create=fx.remaining_calls()>=8)
            if not wake:raise ValueError('diagnosis budget exhausted')
            state.update(stage='awaiting_cto_diagnosis',diagnosis={'wakeup_id':wake['id'],'at':time.time(),'marker':marker})
        except Exception as error:
            state.update(stage='blocked',category='rejection_diagnosis_dispatch_failed',owner=config['cto'],dispatch_error_type=type(error).__name__)
        con.execute('UPDATE harness_repair_tasks SET state=? WHERE source_task=?',(json.dumps(state,sort_keys=True),source))


def resume_replanned_driver(b,source):
    """One author attempt only after the CTO actually reads and changes strategy."""
    with b.LOCK,b.db() as con:
        config,state=map(json.loads,con.execute('SELECT config,state FROM harness_repair_tasks WHERE source_task=?',(source,)).fetchone())
        admission_controls_spike.verify_current(con,config)
        if state['stage']!='guarded_replan_dispatch_intent':return
        plan=state['rejection_replan'];guard=state['staged']['driver_guard']
        if guard.get('replanned_after_rejections'):raise ValueError('replanned attempt consumed')
        settings=json.loads((b.STATE/'native.json').read_text());fx=handoff_runtime.Effects(b,settings)
        try:
            task=native.task_record(settings,state['diagnosis_certificate']['task_id'],config['cto'])
            decision=fx.decision(task)
            if decision!=state['diagnosis_decision'] or decision==plan['prior_diagnosis']['diagnosis_decision'] or decision['action']!='request_test_revision':raise ValueError('changed CTO strategy required')
            if qualify_diagnosis(config,state,task,decision,fx.read_evidence(task))!=state['diagnosis_certificate']:raise ValueError('CTO diagnosis evidence drift')
            if con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone():return
            if fx.remaining_calls()<60:raise ValueError('staged author and review reserve required')
            guard['replanned_after_rejections']={'cto_task':task['id'],'certificate':state['diagnosis_certificate'],
                'rejected_author':plan['author_task'],'operations':plan['operations'],'attempt_limit':1}
            guard['origin_task']=task['id'];state['staged']['cto_task']=task['id']
            state.update(stage='checkpoint_dispatch_intent',category='cto_replanned_guarded_checkpoint1',at=time.time())
        except Exception as error:
            state.update(stage='blocked',category='guarded_replan_evidence_or_reserve_failed',owner=config['cto'],error_type=type(error).__name__)
        con.execute('UPDATE harness_repair_tasks SET state=? WHERE source_task=?',(json.dumps(state,sort_keys=True),source))


def qualify_diagnosis(config,state,task,decision,reads):
    if (task.get('status')!='completed' or task.get('agent_id')!=config['cto']
            or task.get('issue_id')!=state['issue_id'] or task.get('wakeup_id')!=state['diagnosis']['wakeup_id']
            or config['cto']==config['author'] or not isinstance(decision,dict)
            or set(decision)!={'action','reason','optional_files'} or decision['optional_files']!=[]
            or decision['action'] not in ('request_test_revision','escalate_cto')
            or not isinstance(decision['reason'],str) or not 0<len(decision['reason'])<=1200):
        raise ValueError('exact bounded independent diagnosis required')
    if any(type(reads.get(p,{}).get('lines')) is not int or reads[p]['lines']<=0
            or reads[p]['lines']!=reads[p].get('total_lines') for p in diagnosis_paths()):
        raise ValueError('full frozen diagnosis reads required')
    return dict(task_id=task['id'],snapshot=state['snapshot']['volume'],
        test_sha256=state['validation']['test_sha256'],decision_sha256=hashlib.sha256(
            json.dumps(decision,sort_keys=True).encode()).hexdigest(),delivery_approval=False)


def diagnose(b,source):
    with b.LOCK,b.db() as con:
        config,state=map(json.loads,con.execute('SELECT config,state FROM harness_repair_tasks WHERE source_task=?',(source,)).fetchone())
        admission_controls_spike.verify_current(con,config)
        if state.get('diagnosis'):return state['diagnosis']
        if state.get('stage')!='blocked' or state.get('category')!='driver_syntax_error':
            raise ValueError('frozen failed driver repair required')
        if con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone():
            raise ValueError('idle diagnosis required')
        settings=json.loads((b.STATE/'native.json').read_text());fx=handoff_runtime.Effects(b,settings)
        note=diagnosis_note(state);marker=hashlib.sha256((state['author_task']+':driver-diagnosis:'+note).encode()).hexdigest()
        wake=fx.ensure_wakeup(state['issue_id'],config['cto'],state['author_task'],marker,note,allow_create=fx.remaining_calls()>=8)
        if not wake:raise ValueError('diagnosis reserve required')
        state.update(stage='awaiting_cto_diagnosis',diagnosis={'wakeup_id':wake['id'],'at':time.time(),'marker':marker})
        con.execute('UPDATE harness_repair_tasks SET state=? WHERE source_task=?',(json.dumps(state,sort_keys=True),source))
        return state['diagnosis']


def mounts(b,binding):
    with b.db() as con:
        initialize(con);rows=con.execute('SELECT config,state FROM harness_repair_tasks').fetchall()
    for row in rows:
        config,state=map(json.loads,row)
        if state.get('stage')!='awaiting_cto_diagnosis' or binding['issue_id']!=state['issue_id'] or binding['agent_id']!=config['cto']:continue
        with b.db() as con:
            bound=con.execute('SELECT task_id FROM native_bindings WHERE request_id=?',(binding['request_id'],)).fetchone()
        if not bound:raise ValueError('exact native diagnosis binding required')
        task=native.task_record(json.loads((b.STATE/'native.json').read_text()),bound[0],binding['agent_id'])
        if task.get('wakeup_id')!=state['diagnosis']['wakeup_id']:continue
        result=[]
        for volume,identity,target in ((state['snapshot']['volume'],state['author_task'],'candidate'),
                (config['snapshot']['volume'],config['source_task'],'previous')):
            labels=b.docker('GET','/volumes/'+volume)['Labels']
            if labels.get('delivery-kit.owner')!=b.OWNER or labels.get('delivery-kit.source-task')!=identity:
                raise ValueError('immutable diagnosis artifact identity required')
            result.append(dict(Type='volume',Source=volume,Target='/evidence/'+target,ReadOnly=True))
        return result
    return []


def tick(b):
    with b.db() as con:
        initialize(con);rows=con.execute('SELECT source_task,config,state FROM harness_repair_tasks').fetchall()
    settings=json.loads((b.STATE/'native.json').read_text())
    for row in rows:
        source,config,state=row[0],json.loads(row[1]),json.loads(row[2])
        try:import maintenance_delivery
        except ImportError:from broker import maintenance_delivery
        if state.get('stage')=='blocked' and state.get('category')=='maintenance_full_suite_failed' and not state.get('functional_diagnosis'):
            try:maintenance_delivery.register_functional_diagnosis(b,source)
            except Exception as error:
                with b.db() as con:
                    admission_controls_spike.verify_current(con,config)
                    state.update(stage='blocked',category='functional_diagnosis_registration_failed',owner=config['cto'],error_type=type(error).__name__)
                    con.execute('UPDATE harness_repair_tasks SET state=? WHERE source_task=? AND state=?',(json.dumps(state,sort_keys=True),source,row[2]))
            continue
        if maintenance_delivery.advance(b,source,config,state,settings):continue
        if state.get('stage')=='comment_compaction_running':
            if time.time()-state['comment_compaction']['at']>120:
                state['comment_compaction']['status']='interrupted'
                state.update(stage='blocked',category='comment_compaction_interrupted',owner=config['cto'])
                maintenance_delivery.save(b,source,config,state)
            continue
        if (state.get('stage')=='blocked' and state.get('category')=='maintenance_diagnosis_driver_observation'
                and not state.get('c10_decomposition')
                and state.get('envelope_reassessment',{}).get('author_scope_authorized') is True
                and not state.get('functional_correction')):
            with b.db() as con:
                busy=con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone()
            if busy:continue
            try:maintenance_delivery.arm_functional_correction(b,source)
            except Exception as error:
                with b.db() as con:
                    admission_controls_spike.verify_current(con,config)
                    state.update(stage='blocked',category='envelope_author_admission_failed',owner=config['cto'],error_type=type(error).__name__)
                    con.execute('UPDATE harness_repair_tasks SET state=? WHERE source_task=? AND state=?',
                        (json.dumps(state,sort_keys=True),source,row[2]))
            continue
        if state.get('stage')=='rejection_diagnosis_dispatch':
            dispatch_rejection_diagnosis(b,source);continue
        if state.get('stage')=='guarded_replan_dispatch_intent':
            resume_replanned_driver(b,source);continue
        if state.get('stage')=='inspection_in_progress' and time.time()-state.get('inspection_started',time.time())>120:
            blocked=dict(state,stage='blocked',category='interrupted_maintenance_inspection',owner=config['cto'])
            with b.db() as con:
                con.execute('UPDATE harness_repair_tasks SET state=? WHERE source_task=? AND state=?',
                    (json.dumps(blocked,sort_keys=True),source,row[2]))
            continue
        if state.get('stage')=='checkpoint_dispatch_intent':
            dispatch_checkpoint(b,source);continue
        if state.get('stage')=='awaiting_cto_diagnosis':
            fx=handoff_runtime.Effects(b,settings)
            runs=[r for r in native.issue_task_runs(settings,state['issue_id']) if r.get('wakeup_id')==state['diagnosis']['wakeup_id'] and r.get('agent_id')==config['cto']]
            if len(runs)==1 and runs[0]['status'] not in ('queued','dispatched','running'):
                try:
                    decision=fx.decision(runs[0]);proof=qualify_diagnosis(config,state,runs[0],decision,fx.read_evidence(runs[0]))
                    state.update(stage='diagnosis_complete' if decision['action']=='request_test_revision' else 'blocked',
                        diagnosis_decision=decision,diagnosis_certificate=proof,delivery_approval=False)
                    if state.get('functional_diagnosis'):
                        report=maintenance_delivery.qualify_functional_decision(state,decision,proof)
                        state.update(stage='blocked',category='maintenance_diagnosis_'+report['classification'].lower(),
                            functional_diagnosis_receipt=report,owner=config['cto'])
                        if state.get('c10_event_plan_intake'):
                            try:import c10_event_plan as events
                            except ImportError:from broker import c10_event_plan as events
                            state=events.assess(state,report)
                    elif state.get('rejection_replan') and decision['action']=='request_test_revision':
                        state['stage']='guarded_replan_dispatch_intent'
                except (ValueError,KeyError,TypeError):state.update(stage='blocked',category='invalid_or_unread_driver_diagnosis')
            elif len(runs)>1 or time.time()-state['diagnosis']['at']>1800:
                state.update(stage='blocked',category='driver_diagnosis_deadline_or_duplicate')
            else:continue
            with b.db() as con:
                admission_controls_spike.verify_current(con,config)
                con.execute('UPDATE harness_repair_tasks SET state=? WHERE source_task=?',(json.dumps(state,sort_keys=True),source))
            continue
        if state.get('stage')!='awaiting_author':continue
        with b.LOCK:
            with b.db() as con:admission_controls_spike.verify_current(con,config)
            runs=[r for r in native.issue_task_runs(settings,state['issue_id'])
                if r.get('wakeup_id')==state['wakeup_id'] and r.get('agent_id')==config['author']]
            if len(runs)!=1 or runs[0]['status'] in ('queued','dispatched','running'):continue
            task=runs[0]
            pending_seed=None
            with b.db() as con:
                claim=dict(state,stage='inspection_in_progress',inspection_started=time.time())
                changed=con.execute('UPDATE harness_repair_tasks SET state=? WHERE source_task=? AND state=?',
                    (json.dumps(claim,sort_keys=True),source,row[2])).rowcount
                if changed!=1:continue
            try:
                if task['status']!='completed':raise ValueError('author execution failed')
                snap=b.snapshot_submission({'task_id':task['id']})
                name=b.PREFIX+'-maintenance-inspect-'+task['id']
                labels={'delivery-kit.owner':b.OWNER,'delivery-kit.source-task':task['id'],
                    'com.docker.compose.project':b.PREFIX}
                if b.docker('GET','/containers/'+name+'/json'):raise ValueError('interrupted inspection')
                try:
                    b.docker('POST','/containers/create?name='+name,dict(Image=b.OFFLINE_IMAGE,User='10000:10000',
                        Entrypoint=['python3'],Cmd=['-c',inspect.getsource(inspection)+'\ninspection()'],
                        NetworkDisabled=True,Labels=labels,HostConfig=dict(ReadonlyRootfs=True,NetworkMode='none',
                            CapDrop=['ALL'],SecurityOpt=['no-new-privileges'],Memory=268435456,PidsLimit=64,
                            Mounts=[dict(Type='volume',Source=snap['volume'],Target='/candidate',ReadOnly=True),
                                dict(Type='volume',Source=config['snapshot']['volume'],Target='/previous',ReadOnly=True)])))
                    b.docker('POST','/containers/'+name+'/start');deadline=time.time()+20
                    while time.time()<deadline:
                        info=b.docker('GET','/containers/'+name+'/json')
                        if not info['State']['Running']:
                            if info['State']['ExitCode']:raise ValueError('offline inspection failed')
                            facts=json.loads(b.docker_stdout(name,limit=4096));break
                        time.sleep(.2)
                    else:raise ValueError('inspection deadline')
                finally:
                    info=b.docker('GET','/containers/'+name+'/json')
                    if info and all(info['Config']['Labels'].get(k)==v for k,v in labels.items() if k.startswith('delivery-kit.')):
                        b.docker('DELETE','/containers/'+name+'?force=true')
                category=classification(facts)
                current_seed=state.get('functional_correction',{}).get('seed')
                if state.get('functional_fragment_recovery'):
                    try:import maintenance_delivery
                    except ImportError:from broker import maintenance_delivery
                    current_seed=maintenance_delivery.fragment_seed(state)
                if state.get('c10_checkpoints'):
                    cp=state['c10_checkpoints'];current_seed=cp.get('execution_seed',cp['seed'])
                if current_seed and facts['test_sha256']==current_seed['validation']['test_sha256']:
                    category='unchanged_functional_driver'
                state.update(stage='awaiting_independent_review' if category=='independent_review_required' else 'blocked',
                    category=category,validation=facts,snapshot=snap,author_task=task['id'],owner=config['cto'],delivery_approval=False)
                if state.get('staged') and state['staged']['current']==1 and checkpoint_passed(facts):
                    receipt={'task_id':task['id'],'snapshot':snap,'validation':facts,'checkpoint':1}
                    state['staged']['history'].append(receipt);state['staged']['current']=2
                    state['stage']='checkpoint_dispatch_intent'
                    pending_seed={'source':source,'receipt':receipt}
                elif state.get('staged',{}).get('current')==2 and checkpoint_passed(facts) and category=='independent_review_required':
                    state.update(stage='maintenance_suite_pending',category='controller_full_suite_required',at=time.time())
            except Exception as error:
                state.update(stage='blocked',category='maintenance_inspection_failed',error_type=type(error).__name__,
                    error_reason=str(error)[:180],author_task=task['id'],owner=config['cto'],delivery_approval=False)
            with b.db() as con:
                admission_controls_spike.verify_current(con,config)
                if pending_seed:
                    trial=json.loads(con.execute('SELECT config FROM test_revision_trials WHERE issue_id=?',(state['issue_id'],)).fetchone()[0])
                    trial['maintenance_seed']=pending_seed
                    con.execute('UPDATE test_revision_trials SET config=? WHERE issue_id=?',(json.dumps(trial,sort_keys=True),state['issue_id']))
                con.execute('UPDATE harness_repair_tasks SET state=? WHERE source_task=?',(json.dumps(state,sort_keys=True),source))


def registered_author(con, issue, author):
    """A paused maintenance route is not a generic dispatch authorization."""
    if not con.execute("SELECT 1 FROM sqlite_master WHERE name='harness_repair_tasks'").fetchone():
        return False
    for row in con.execute('SELECT config,state FROM harness_repair_tasks'):
        config,state=map(json.loads,row)
        if (state.get('issue_id')==issue and config.get('author')==author
                and state.get('stage') in ('prepared','awaiting_author')
                and state.get('cto_task') and state.get('delivery_approval') is False):
            trial=con.execute('SELECT config FROM test_revision_trials WHERE issue_id=?',(issue,)).fetchone()
            return bool(trial and json.loads(trial[0]).get('harness_maintenance_only') is True)
    return False


def preparation_marker(source, certificate, note):
    return hashlib.sha256((source+':isolated-driver-maintenance:'+certificate['decision_sha256']+
        ':'+hashlib.sha256(note.encode()).hexdigest()).encode()).hexdigest()


def maintenance_prompt(instruction):
    start=instruction.index('\nDELIVERY_TEST_ARTIFACT_V1:')
    return ('FIXTURE MAINTENANCE PHASE. Edit only the declared NEW test. Preserve '
        'every existing method and assertion; product and baseline files stay read-only. '
        'Repair the CTO-diagnosed driver only. The controller performs syntax checks and '
        'executes the full pinned suite on the immutable submission. Do not request a '
        'compiler, terminal or shell, and do not claim tests executed by you. '
        'A syntax repair is not functional TDD Red, product implementation or delivery. '
        'Independent frozen-artifact validation/review is required. Do not fabricate '
        'reports, remove tests, alter discovery, skip failures or implement product.'+instruction[start:])


def current_diagnosis_context(con,issue,task):
    if not con.execute("SELECT 1 FROM sqlite_master WHERE name='harness_repair_tasks'").fetchone():
        raise ValueError('registered current diagnosis required')
    selected=[]
    for row in con.execute('SELECT config,state FROM harness_repair_tasks'):
        config,state=map(json.loads,row)
        if state.get('issue_id')!=issue['id'] or config.get('cto')!=task.get('agent_id'):continue
        plan=state.get('functional_diagnosis',{});note=plan.get('note','')
        if ('DELIVERY_CURRENT_HARNESS_DIAGNOSIS_V1' not in note or state.get('stage')!='awaiting_cto_diagnosis'
                or task.get('issue_id')!=issue['id'] or not (task.get('id') or task.get('task_id'))
                or task.get('wakeup_id')!=state.get('diagnosis',{}).get('wakeup_id')
                or note not in (task.get('handoff_note') or '')):
            raise ValueError('exact active current diagnosis required')
        selected.append({'title':'Current readonly CTO contract review','description':note,'handoff_note':note})
    if len(selected)!=1:raise ValueError('one current diagnosis required')
    return selected[0]


def current_maintenance_context(con,issue,task):
    """Native runtime phase overrides historical issue prose, never grants access."""
    if not con.execute("SELECT 1 FROM sqlite_master WHERE name='harness_repair_tasks'").fetchone():
        raise ValueError('current maintenance registration required')
    try:import driver_checkpoint_policy,maintenance_delivery
    except ImportError:from broker import driver_checkpoint_policy,maintenance_delivery
    selected=[]
    for row in con.execute('SELECT config,state FROM harness_repair_tasks'):
        config,state=map(json.loads,row)
        grant=driver_checkpoint_policy.select(config,state,issue['id'],task)
        if grant:
            if state.get('c10_checkpoints'):
                try:import c10_checkpoint_contract as gates
                except ImportError:from broker import c10_checkpoint_contract as gates
                note=gates.admission(state).author_note(state)
            else:
                note=maintenance_delivery.functional_correction_note(state) if state.get('functional_correction') else checkpoint_note(state['staged']['current'],state['diagnosis_decision'])
            selected.append({'title':'Active controller-verified harness maintenance',
                'description':'CURRENT PHASE ONLY. Historical issue instructions are archived, not active. '+note,
                'handoff_note':note})
    if len(selected)!=1:raise ValueError('one exact active maintenance phase required')
    return selected[0]


def bounded_correction_note(note, measurement):
    """Keep the ordinary final-size gate; never authorize a larger file."""
    size=measurement.get('bytes')
    digest=measurement.get('sha256')
    if (type(size) is not int or not 0<size<=32768 or not isinstance(digest,str)
            or len(digest)!=64 or any(x not in '0123456789abcdef' for x in digest)):
        raise ValueError('admissible measured source required')
    return (note+'\nMEASURED SIZE CONTRACT: original file '+str(size)+' UTF-8 bytes, SHA256 '+digest+
        '; final write limit 32768 bytes; remaining growth '+str(32768-size)+' bytes. '
        'The previous patch attempts were rejected by the write fence and changed nothing. '
        'Keep the WHOLE resulting file <=32768 UTF-8 bytes, not merely the patch. '
        'Use concise driver code; if space is needed compact comments/blank lines without '
        'removing or changing methods/assertions or fabricating report values. '
        'After a failed write, do not repeat the same patch: check its final size and '
        'change the proposal. Verify the actual file changed and run the full pinned suite. '
        'If a provider/tool error occurs, report failure; never claim successful repair.')


def resume_bounded(b, source, measurement):
    """One changed-contract retry after controller-measured admissible input."""
    with b.LOCK,b.db() as con:
        config,state=map(json.loads,con.execute('SELECT config,state FROM harness_repair_tasks WHERE source_task=?',(source,)).fetchone())
        admission_controls_spike.verify_current(con,config)
        if state.get('bounded_retry'):
            return {k:state.get(k) for k in ('stage','identifier','wakeup_id')}
        if state.get('stage')!='blocked' or state.get('category')!='unchanged_invalid_driver':
            raise ValueError('unchanged invalid maintenance required')
        if (measurement.get('task_id')!=state.get('author_task')
                or measurement.get('volume')!=state['snapshot']['volume']
                or measurement.get('sha256')!=state['validation']['test_sha256']
                or measurement.get('sha256')!=config['file_sha256']['tests/test_incremental_u3.py']):
            raise ValueError('measurement identity drift')
        if con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone():
            raise ValueError('idle maintenance required')
        settings=json.loads((b.STATE/'native.json').read_text())
        runs=native.issue_task_runs(settings,state['issue_id'])
        old=next((r for r in runs if r['id']==state['author_task']),{})
        if old.get('status')!='completed' or old.get('agent_id')!=config['author'] or old.get('wakeup_id')!=state['wakeup_id']:
            raise ValueError('exact terminal maintenance required')
        if any(r.get('status') in ('queued','dispatched','running') for r in runs):
            raise ValueError('idle native maintenance required')
        note=bounded_correction_note(state['note'],measurement)
        marker=hashlib.sha256((state['marker']+':measured-bounded-correction:'+note).encode()).hexdigest()
        fx=handoff_runtime.Effects(b,settings)
        if fx.remaining_calls()<40:raise ValueError('maintenance review reserve required')
        wake=native.ensure_unit_start(settings,state['issue_id'],config['author'],state['cto_task'],marker,note,allow_create=True)
        state.update(stage='awaiting_author',bounded_retry={'measurement':measurement,'previous_wakeup':state['wakeup_id'],
            'previous_task':state['author_task'],'note_sha256':hashlib.sha256(note.encode()).hexdigest()},
            wakeup_id=wake['id'],at=time.time())
        con.execute('UPDATE harness_repair_tasks SET state=? WHERE source_task=?',(json.dumps(state,sort_keys=True),source))
        return {k:state.get(k) for k in ('stage','identifier','wakeup_id')}


def prepare(b,source):
    with b.LOCK:
        with b.db() as con:
            initialize(con)
            prior=con.execute('SELECT config,state FROM harness_repair_tasks WHERE source_task=?',(source,)).fetchone()
            config,state=map(json.loads,con.execute('SELECT config,state FROM harness_prerequisites WHERE source_task=?',(source,)).fetchone())
            admission_controls_spike.verify_current(con,config)
            if prior:return json.loads(prior[1])
            if state['stage']!='repair_sponsored' or state['decision']['action']!='request_test_revision':
                raise ValueError('authentic prerequisite sponsorship required')
            if con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone():
                raise ValueError('idle fixture maintenance required')
        settings=json.loads((b.STATE/'native.json').read_text());fx=handoff_runtime.Effects(b,settings)
        task=native.task_record(settings,state['task_id'],config['cto'])
        decision=fx.decision(task)
        certificate=harness_prerequisite.qualify(config,state,task,decision,fx.read_evidence(task))
        if decision!=state['decision'] or certificate!=state['certificate']:raise ValueError('sponsorship drift')
        if fx.remaining_calls()<40:raise ValueError('maintenance plus review reserve required')
        marker=preparation_marker(source,certificate,author_note(config,decision))
        issues=NativeIssues(settings);parent=issues.request('/issues/'+config['issue_id'])
        desired=dict(title='Harness prerequisite repair '+marker[:12],description=author_note(config,decision),
            parent_issue_id=config['issue_id'],project_id=parent.get('project_id'),stage=1,status='todo')
        issue=issues.ensure(desired);child=issue['id']
        with b.db() as con:
            route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(config['issue_id'],)).fetchone()[0])
            red=json.loads(con.execute('SELECT receipt FROM test_first_red WHERE issue_id=?',(config['issue_id'],)).fetchone()[0])
            paths=[r[0] for r in con.execute('SELECT path FROM issue_editables WHERE issue_id=?',(config['issue_id'],))]
            command=con.execute('SELECT command FROM issue_test_commands WHERE issue_id=?',(config['issue_id'],)).fetchone()[0]
        base=b.issue_base(config['issue_id']);volume=b.PREFIX+'-base-'+child
        labels={'delivery-kit.owner':b.OWNER,'delivery-kit.issue-id':child,'delivery-kit.base-sha':base['base_sha'],
            'com.docker.compose.project':b.PREFIX,'com.docker.compose.service':'harness-maintenance-base'}
        existing=b.docker('GET','/volumes/'+volume)
        if existing and any(existing['Labels'].get(k)!=v for k,v in labels.items()):raise ValueError('foreign maintenance base')
        if not existing:b.docker('POST','/volumes/create',dict(Name=volume,Labels=labels))
        name=b.PREFIX+'-harness-base-copy-'+child
        if b.docker('GET','/containers/'+name+'/json'):raise ValueError('interrupted maintenance copy')
        try:
            helper=b.docker('GET','/containers/'+b.PREFIX+'-execution-broker-1/json')['Image']
            b.docker('POST','/containers/create?name='+name,dict(Image=helper,User='10000:10000',
                Entrypoint=['python3'],Env=['PYTHONPATH=/','PYTHONDONTWRITEBYTECODE=1'],
                Cmd=['-c','from pathlib import Path;import base_copy;base_copy.TARGET=Path("/revision");base_copy.main()'],
                NetworkDisabled=True,Labels=labels,HostConfig=dict(ReadonlyRootfs=True,NetworkMode='none',
                    CapDrop=['ALL'],SecurityOpt=['no-new-privileges'],Memory=268435456,PidsLimit=64,
                    Mounts=[dict(Type='volume',Source=base['volume'],Target='/source',ReadOnly=True),
                        dict(Type='volume',Source=volume,Target='/revision',ReadOnly=False)])))
            b.docker('POST','/containers/'+name+'/start');deadline=time.time()+25
            while time.time()<deadline:
                info=b.docker('GET','/containers/'+name+'/json')
                if not info['State']['Running']:
                    if info['State']['ExitCode']:raise ValueError('maintenance base copy failed')
                    break
                time.sleep(.2)
            else:raise ValueError('maintenance base deadline')
        finally:
            info=b.docker('GET','/containers/'+name+'/json')
            if info and all(info['Config']['Labels'].get(k)==v for k,v in labels.items() if k.startswith('delivery-kit.')):
                b.docker('DELETE','/containers/'+name+'?force=true')
        b.register_issue_base(dict(issue_id=child,base_sha=base['base_sha'],volume=volume,manifest_sha256=base['manifest_sha256']))
        b.register_issue_editables(dict(issue_id=child,paths=paths,test_command=command))
        handoff_runtime.register(b,dict(route,issue_id=child,enabled=False))
        trial=dict(issue_id=child,parent_issue=config['issue_id'],reviewer=route['techlead'],base_sha=base['base_sha'],
            cto_decision=task['id'],reason=decision['reason'],old_red=red,seed_previous_tests=True,seeded_edit_required=True,
            harness_maintenance_only=True,historic_functional_red=False)
        prepared=dict(issue_id=child,identifier=issue.get('identifier'),stage='prepared',marker=marker,
            note=author_note(config,decision),delivery_approval=False,cto_task=task['id'])
        with b.db() as con:
            admission_controls_spike.verify_current(con,config)
            con.execute('INSERT INTO test_revision_trials VALUES (?,?,?,?)',
                (child,config['issue_id'],json.dumps(trial,sort_keys=True),'{}'))
            con.execute('INSERT INTO harness_repair_tasks VALUES (?,?,?)',(source,json.dumps(config,sort_keys=True),json.dumps(prepared,sort_keys=True)))
        return prepared


def dispatch(b,source):
    with b.LOCK,b.db() as con:
        config,state=map(json.loads,con.execute('SELECT config,state FROM harness_repair_tasks WHERE source_task=?',(source,)).fetchone())
        admission_controls_spike.verify_current(con,config)
        if state.get('wakeup_id'):return {k:state.get(k) for k in ('stage','issue_id','identifier','wakeup_id')}
        if state['stage']!='prepared':raise ValueError('prepared maintenance required')
        route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(state['issue_id'],)).fetchone()[0])
        if route['enabled'] or con.execute('SELECT 1 FROM test_first_red WHERE issue_id=?',(state['issue_id'],)).fetchone():
            raise ValueError('paused tests-only maintenance required')
        settings=json.loads((b.STATE/'native.json').read_text());fx=handoff_runtime.Effects(b,settings)
        wake=native.ensure_unit_start(settings,state['issue_id'],config['author'],state['cto_task'],state['marker'],state['note'],allow_create=fx.remaining_calls()>=40)
        if not wake:return dict(stage='budget_wait',delivery_approval=False)
        state.update(stage='awaiting_author',wakeup_id=wake['id'],at=time.time())
        con.execute('UPDATE harness_repair_tasks SET state=? WHERE source_task=?',(json.dumps(state,sort_keys=True),source))
        return {k:state.get(k) for k in ('stage','issue_id','identifier','wakeup_id')}
