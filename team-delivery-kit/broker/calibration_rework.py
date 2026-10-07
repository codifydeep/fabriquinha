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


def instruction(config,state):
    peer=state['stage'].startswith('peer')
    note=('DELIVERY_STRUCTURED_DECISION_V1:technical\nDELIVERY_CALIBRATION_REWORK_V1\n'
        'DELIVERY_TYPED_DECISION_V1\nDELIVERY_TECHNICAL_LENGTH_FEEDBACK_V1\n'
        'CALIBRATION GATE REWORK: '+('independent Tech Lead inspection of CTO proposal. ' if peer else 'CTO diagnosis. ')+
        'Read every immutable candidate file completely. No shell, edits, Red replay or approval of delivery. '
        'The controller rejected this candidate before Red; a failed positive reference is not product Red. '
        'Diagnose the NEW harness and preserve every existing method/assertion and all original acceptance. '
        'Only the original author may execute a tests-only rework after BOTH independent decisions. '
        'A request sponsors one changed-evidence gate rework, never an identical retry, budget/depth reset, '
        'baseline edit, product edit, merge or homologation.\nEvidence: '+json.dumps(config['diagnostic'],sort_keys=True)+
        ('\nCTO proposal: '+json.dumps(state['cto_decision'],sort_keys=True) if peer else '')+
        '\nUnchanged acceptance IDs: '+','.join(sorted(config['criteria']))+
        '\nReturn ONLY JSON action=request_test_revision or escalate_cto, reason<=1200 characters, optional_files=[]. '
        'Explain a concrete observation-preserving correction; if evidence is insufficient escalate, never guess.\n'+
        ''.join('DELIVERY_REVIEW_READ_PATH:'+p+'\n' for p in config['paths']))
    if len(note)+100>4000:raise ValueError('calibration diagnosis context too large')
    return note


def marker(config,role):
    return digest({'source':config['source_task'],'manifest':config['manifest_sha256'],'role':role,
        'operation':'calibration_rework_v1','format_revision':config.get('format_revision',0)})


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
    if (decision.get('action')!='request_test_revision' or decision.get('optional_files')!=[]
            or not isinstance(decision.get('reason'),str) or not 1<=len(decision['reason'])<=1200
            or any(type(reads.get(p,{}).get('lines')) is not int or reads[p]['lines']<=0
                   or reads[p]['lines']!=reads[p].get('total_lines') for p in config['paths'])):
        raise ValueError('actual complete reads and concrete independent sponsorship required')
    return task['id'],decision


def advance(config,state,runs,effects,persist,now=None):
    now=time.time() if now is None else now
    if state['stage'] in ('blocked','author_dispatched'):return state
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
                'observation, not the product. Run the full pinned suite; the controller must capture '
                'calibration and genuine Red before independent test review and implementation. '
                'This is one gate rework; no iteration/size/depth change or recursive revision. No promise-only completion.')
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
            state={**state,role+'_task':task,role+'_decision':value,'stage':'peer_pending' if role=='cto' else 'author_pending'}
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
    if existing and existing[0]!=key:return False  # A new author still follows normal Red capture.
    if not existing:
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
            diagnostic={k:proof[k] for k in ('phase','manifest_sha256','test_sha256','positive')}
        if diagnostic.get('manifest_sha256')!=identity['manifest_sha256']:raise ValueError('exact calibration diagnostic manifest required')
        config=dict(issue_id=issue,source_task=key,author=route['author'],cto=route['cto'],peer=route['techlead'],
            manifest_sha256=identity['manifest_sha256'],volume=identity['volume'],diagnostic=diagnostic,
            contract_sha256=route['contract_sha256'],criteria=value['criteria'],minimum_calls=route['minimum_calls'],
            paths=sorted('/evidence/candidate/'+p for p in set(route['test_first_files'])|{'app/static/app.js'}))
        state=dict(stage='cto_pending',delivery_approval=False,revision_depth_reset=False,attempt_limit=1)
        instruction(config,state)
        with b.LOCK,b.db() as con:
            if con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','active','closing')").fetchone():return True
            con.execute('INSERT INTO calibration_reworks VALUES(?,?,?,?)',(issue,key,json.dumps(config,sort_keys=True),json.dumps(state,sort_keys=True)))
    else:config,state=map(json.loads,existing[1:])
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
            or any(route[k]!=config[v] for k,v in (('author','author'),('cto','cto'),('techlead','peer')))):return True
    try:advance(config,state,runs,effects,persist)
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
