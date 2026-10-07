"""One independently sponsored, hash-bound V5 execution; never a gate waiver."""
import hashlib,json,re,time

FLAGS=('actual_registry','actual_default_selection','actual_acp_selection','full_proxy_request_validation',
       'readless_edit_denied','generic_write_and_terminal_denied','python_denied','direct_handler_fenced',
       'outside_template_change_preserves_bytes','test_weakening_preserves_bytes',
       'invalid_syntax_preserves_bytes','stale_edit_denied','template_selector_denied','fixed_node_check','credentials_absent')

def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def validate_qualification(proof):
    if (proof.get('schema')!='surgical-template-registry-probe-v5' or proof.get('status')!='passed'
            or proof.get('uid')!=10000 or proof.get('network')!='none' or proof.get('model_calls')!=0
            or proof.get('delivery_approval') is not False or any(proof.get(k) is not True for k in FLAGS)
            or any(not re.fullmatch(r'sha256:[a-f0-9]{64}',str(proof.get(k,''))) for k in ('worker_image','proxy_image'))):
        raise ValueError('qualified installed V5 registry required')

def note(config,state):
    return ('CURRENT R1 BOUNDED TEMPLATE CORRECTION. This is the independently sponsored changed-evidence '
        'execution, not an identical retry or limit reset. Edit ONLY NODE_HARNESS_TEMPLATE in the declared NEW '
        'test using surgical_test_edit; no terminal, Python, generic writes, patches, assertions or product edits. '
        'Read the whole assigned test and product first. Repair terminal observation AFTER async settlement; '
        'keep pending observation separate. The original product lacks the feature: expected Red, not Green. '
        'Save and inspect the correction, then finish for controller calibration, full Red and independent review. '
        'Do not claim those gates ran. No Red reconstruction, test skipping, depth/size/iteration change or delivery approval. '
        'CTO proposal: '+state['cto_decision']['reason']+'. Independent Tech Lead: '+state['peer_decision']['reason']+
        '\nDELIVERY_CONTROLLER_CALIBRATION_V1\n')

def marker(config,state):
    return digest(dict(operation='bounded_template_author_v5',source=config['source_task'],
                       executor=state['executor']['contract_sha256']))

def arm(b,source,qualification):
    validate_qualification(qualification)
    try:import native,handoff_runtime
    except ImportError:from broker import native,handoff_runtime
    with b.LOCK:
        with b.db() as con:
            row=con.execute('SELECT config,state FROM calibration_failure_plans WHERE source_task=?',(source,)).fetchone()
            if not row:raise ValueError('independent proposal required')
            config,state=map(json.loads,row)
            if state.get('executor'):
                if state['executor']['qualification']!=qualification:raise ValueError('one immutable executor qualification required')
                return state['executor']
            route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(config['issue_id'],)).fetchone()[0])
            if (state['stage']!='plan_qualified' or not route['enabled'] or route['contract_sha256']!=config['contract_sha256']
                    or b.IMAGE!=qualification['worker_image']
                    or con.execute('SELECT 1 FROM test_first_red WHERE issue_id=?',(config['issue_id'],)).fetchone()
                    or con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','active','closing')").fetchone()):
                raise ValueError('idle exact current pre-Red proposal required')
        proxy=b.docker('GET','/containers/'+b.PREFIX+'-model-proxy-1/json')
        if (not proxy or proxy['Image']!=qualification['proxy_image'] or not proxy['State']['Running']
                or proxy['Config']['Labels'].get('com.docker.compose.project')!=b.PREFIX):
            raise ValueError('qualified installed proxy required')
        settings=json.loads((b.STATE/'native.json').read_text());fx=handoff_runtime.Effects(b,settings)
        runs=native.issue_task_runs(settings,config['issue_id'])
        authors=[r for r in runs if r.get('agent_id')==config['author']]
        if (not authors or max(authors,key=lambda r:(r.get('created_at') or '',r['id']))['id']!=source
                or next(r for r in authors if r['id']==source)['status']!='failed'
                or any(r['status'] in ('queued','dispatched','running') for r in runs)):
            raise ValueError('unchanged failed author and idle tasks required')
        for role in ('cto','peer'):
            task=native.task_record(settings,state[role+'_task'],config[role]);reads=fx.read_evidence(task)
            if (task['status']!='completed' or task.get('issue_id')!=config['issue_id'] or task.get('agent_id')!=config[role]
                    or task.get('wakeup_id')!=state[role+'_wakeup']
                    or fx.decision(task)!=state[role+'_decision']
                    or any(reads.get(p,{}).get('lines',0)<=0 or reads[p]['lines']!=reads[p].get('total_lines') for p in config['paths'])):
                raise ValueError('exact actual independent full-read sponsorship required')
        contract=dict(source=source,manifest=config['manifest_sha256'],test_sha256=config['diagnostic']['test_sha256'],
            author=config['author'],cto_task=state['cto_task'],cto_decision=state['cto_decision'],
            peer_task=state['peer_task'],peer_decision=state['peer_decision'],criteria=config['criteria'],
            unchanged_delivery_contract=config['contract_sha256'],qualification_sha256=digest(qualification))
        executor=dict(status='ready',qualification=qualification,contract=contract,contract_sha256=digest(contract),
            surgical=dict(path='/workspace/tests/test_service_mode_indicator.py',expected_sha256=contract['test_sha256'],protocol='typed_template_v5'),
            worker_image=qualification['worker_image'],attempt_limit=1,delivery_approval=False)
        if len(note(config,state))+100>4000:raise ValueError('bounded exact executor handoff required')
        with b.db() as con:
            current=con.execute('SELECT config,state FROM calibration_failure_plans WHERE source_task=?',(source,)).fetchone()
            if tuple(current)!=tuple(row):raise ValueError('proposal changed during qualification')
            state['executor']=executor
            con.execute('UPDATE calibration_failure_plans SET state=? WHERE source_task=?',(json.dumps(state,sort_keys=True),source))
        return executor

def advance(config,state,effects,persist):
    executor=state.get('executor')
    if not executor or executor['status'] not in ('ready','intent'):return state
    if effects.remaining_calls()<config['minimum_calls'] or not effects.implementation_available(config['issue_id'],config['author']):return state
    first=executor['status']=='ready'
    if first:
        state={**state,'executor':{**executor,'status':'intent','intent_at':time.time()}};persist(state)
    wake=effects.ensure_wakeup(config['issue_id'],config['author'],state['peer_task'],marker(config,state),note(config,state),allow_create=first)
    if wake:state={**state,'executor':{**state['executor'],'status':'waiting','wakeup_id':wake['id']}};persist(state)
    elif time.time()-state['executor']['intent_at']>=1800:
        state={**state,'executor':{**state['executor'],'status':'blocked','required_action':'observe_unknown_template_dispatch_no_repost'}};persist(state)
    return state

def for_task(b,issue,task):
    with b.db() as con:
        if not con.execute("SELECT 1 FROM sqlite_master WHERE name='calibration_failure_plans'").fetchone():return None
        rows=con.execute('SELECT config,state FROM calibration_failure_plans').fetchall()
    matches=[(json.loads(c),json.loads(s)) for c,s in rows if json.loads(c)['issue_id']==issue and json.loads(s).get('executor')]
    if not matches:return None
    if len(matches)!=1:raise ValueError('one template executor per issue required')
    config,state=matches[0];executor=state['executor']
    identity=task.get('id') or task.get('task_id')
    if task.get('id') and task.get('task_id') and task['id']!=task['task_id']:
        raise ValueError('conflicting template execution identity')
    if task.get('agent_id')!=config['author'] or identity==config['source_task']:return None
    if executor['status'] not in ('intent','waiting'):return None
    # session_operation supplies a verified native binding, not a task record.
    # Resolve status from the native source; never infer liveness from omission.
    if 'status' not in task:
        if not identity:raise ValueError('template execution identity required')
        try:import native
        except ImportError:from broker import native
        settings=json.loads((b.STATE/'native.json').read_text())
        actual=native.task_record(settings,identity,config['author'])
        if (actual.get('id')!=identity or any(actual.get(k)!=task.get(k)
                for k in ('agent_id','issue_id','wakeup_id'))):
            raise ValueError('template binding differs from native task')
        task=actual
    if task.get('status') not in ('queued','dispatched','running'):return None
    wake=executor.get('wakeup_id')
    if not wake:
        try:import native
        except ImportError:from broker import native
        settings=json.loads((b.STATE/'native.json').read_text())
        observed=native.ensure_task_handoff(settings,issue,config['author'],state['peer_task'],marker(config,state),note(config,state),allow_create=False)
        wake=observed['id'] if observed else None
    if task.get('issue_id')!=issue or not wake or task.get('wakeup_id')!=wake:raise ValueError('exact template author wakeup required')
    return dict(worker_image=executor['worker_image'],surgical=executor['surgical'])

def worker_config(b,request,issue):
    with b.db() as con:
        if not con.execute("SELECT 1 FROM sqlite_master WHERE name='calibration_failure_plans'").fetchone():return None
        rows=con.execute('SELECT config,state FROM calibration_failure_plans').fetchall()
        if not any(json.loads(c)['issue_id']==issue and json.loads(s).get('executor') for c,s in rows):return None
        bound=con.execute('SELECT task_id,agent_id FROM native_bindings WHERE request_id=?',(request,)).fetchone()
    if not bound:raise ValueError('template native binding required')
    try:import native
    except ImportError:from broker import native
    return for_task(b,issue,native.task_record(json.loads((b.STATE/'native.json').read_text()),bound[0],bound[1]))

def observe(b,route,source):
    """Execution completion is not Red or delivery; never leave a terminal dispatch waiting."""
    if source.get('status') not in ('completed','failed'):return
    with b.db() as con:
        if not con.execute("SELECT 1 FROM sqlite_master WHERE name='calibration_failure_plans'").fetchone():return
        rows=con.execute('SELECT source_task,config,state FROM calibration_failure_plans').fetchall()
    selected=[r for r in rows if json.loads(r[1])['issue_id']==route['issue_id'] and
        json.loads(r[2]).get('executor',{}).get('status')=='waiting' and
        json.loads(r[2])['executor'].get('wakeup_id')==source.get('wakeup_id')]
    if not selected:return
    if len(selected)!=1 or source.get('agent_id')!=route['author']:raise ValueError('exact terminal template author required')
    try:import handoffs
    except ImportError:from broker import handoffs
    key,_,raw=selected[0];state=json.loads(raw)
    state['executor'].update(status='author_completed_awaiting_gates' if source['status']=='completed' else 'blocked',
        task_id=source['id'],delivery_approval=False,required_action='controller_calibration_and_red' if source['status']=='completed' else 'CTO_diagnose_new_failed_execution_no_identical_retry')
    with b.LOCK,b.db() as con:
        current=con.execute('SELECT state FROM calibration_failure_plans WHERE source_task=?',(key,)).fetchone()
        if current[0]!=raw:return
        con.execute('UPDATE calibration_failure_plans SET state=? WHERE source_task=?',(json.dumps(state,sort_keys=True),key))
        row=handoffs.load(con,key)
        if row:
            data=json.loads(row['data']);data['calibration_failure_plan']['state']=state
            data['required_action']=state['executor']['required_action']
            handoffs.save(con,key,route['issue_id'],'calibration_failure_plan',route['cto'] if source['status']=='failed' else route['author'],data,time.time())
