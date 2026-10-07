"""Evidence-bound post-denial CTO/peer planning, never an author retry.

Each failed native execution owns one persistent diagnostic intent. Historical
executors and plans remain intact; a new image alone cannot sponsor execution.
"""
import hashlib,json,time


def modules():
    try:import template_author_executor as executor,template_admission_recovery as admission,calibration_rework as lane,harness_qualification as jobs,handoffs,native
    except ImportError:from broker import template_author_executor as executor,template_admission_recovery as admission,calibration_rework as lane,harness_qualification as jobs,handoffs,native
    return executor,admission,lane,jobs,handoffs,native


def denials(messages):
    """Require native call/result pairs; prose and truncated results cannot qualify."""
    uses=[m for m in messages if m.get('type')=='tool_use']
    calls=[m for m in uses if m.get('tool')=='surgical_test_edit']
    results=[m for m in messages if m.get('type')=='tool_result' and m.get('tool')=='surgical_test_edit']
    ids=[m.get('call_id') for m in calls]
    if (not any(m.get('tool')=='read_file' for m in uses)
            or any(m.get('tool') not in ('read_file','surgical_test_edit') for m in uses)
            or len(calls)!=2 or len(results)!=2 or any(not isinstance(i,str) or not i for i in ids)
            or len(set(ids))!=2 or {m.get('call_id') for m in results}!=set(ids)):
        raise ValueError('two paired actual surgical denials and reads required')
    records=[]
    for call in calls:
        result=next(m for m in results if m.get('call_id')==call['call_id'])
        output=result.get('output','')
        if (result.get('output_truncated') or not isinstance(output,str) or len(output)>4096
                or not output.startswith('surgical_test_edit failed: surgical_edit_rejected:')):
            raise ValueError('complete failed tool results required')
        category=output.split(':',2)[2].split(':',1)[0]
        if category not in ('file_size_exceeded','replacement_not_unique_or_bounded'):
            raise ValueError('distinct size/selection evidence required')
        records.append(dict(call_id=call['call_id'],category=category,
                            output_sha256=hashlib.sha256(output.encode()).hexdigest()))
    if [r['category'] for r in records]!=['file_size_exceeded','replacement_not_unique_or_bounded']:
        raise ValueError('ordered size denial followed by fragment denial required')
    return dict(operation='surgical_failure_diagnosis_v1',results=records,
                author_retry_authorized=False,delivery_approval=False)


def bootstrap_evidence(b,con,source,issue,author,held,messages):
    """Only an authenticated worker that never started; no prose-derived retry."""
    if any(m.get('type') in ('tool_use','tool_result') for m in messages):
        raise ValueError('bootstrap incident cannot contain executed tools')
    rows=con.execute('SELECT n.request_id,g.used,g.mode,l.name,l.status FROM native_bindings n '
        'JOIN grants g USING(request_id) JOIN leases l USING(request_id) '
        'WHERE n.task_id=? AND n.issue_id=? AND n.agent_id=?',(source,issue,author)).fetchall()
    if len(rows)!=1 or rows[0][1]!=1 or rows[0][2]!='implementation' or rows[0][4]!='failed':
        raise ValueError('one consumed failed implementation bootstrap required')
    request,_,_,name,_=rows[0]
    errors=[tuple(r) for r in con.execute('SELECT operation,category FROM broker_errors WHERE request_id=?',(request,))]
    if ('worker_submit','bootstrap:docker_containers_create') not in errors:
        raise ValueError('recorded pre-start create failure required')
    if con.execute('SELECT 1 FROM acp_events WHERE request_id=?',(request,)).fetchone():
        raise ValueError('bootstrap recovery cannot replay an initialized execution')
    info=b.docker('GET','/containers/'+name+'/json')
    labels=(info or {}).get('Config',{}).get('Labels',{})
    state=(info or {}).get('State',{})
    executor,_,_,_,_,_=modules();previous=executor.selected_executor(held)
    if (not info or info['Image']!=previous['worker_image'] or state.get('Status')!='created'
            or state.get('Running') is not False or not str(state.get('StartedAt','')).startswith('0001-')
            or info.get('ExecIDs') or labels.get('delivery-kit.owner')!=b.OWNER
            or labels.get('delivery-kit.request')!=request):
        raise ValueError('exact owned never-started worker required')
    return dict(operation='worker_bootstrap_failure_v1',source_task=source,request_id=request,
        container_id=info['Id'],worker_image=info['Image'],category='docker_create_ack_timeout',
        worker_never_started=True,acp_events=0,tool_calls=0,
        author_retry_authorized=False,delivery_approval=False)


def installed_line_qualification(b,con):
    if not con.execute("SELECT 1 FROM sqlite_master WHERE name='template_registry_qualifications'").fetchone():
        raise ValueError('installed V6 qualification required before infrastructure replan')
    row=con.execute('SELECT receipt FROM template_registry_qualifications WHERE worker_image=?',(b.IMAGE,)).fetchone()
    if not row:raise ValueError('exact installed V6 qualification missing')
    proof=json.loads(row[0]);executor,_,_,_,_,_=modules();executor.validate_line_qualification(proof)
    proxy=b.docker('GET','/containers/'+b.PREFIX+'-model-proxy-1/json')
    if (proof['worker_image']!=b.IMAGE or not proxy or proxy['Image']!=proof['proxy_image'] or not proxy['State']['Running']
            or proxy.get('Config',{}).get('Labels',{}).get('com.docker.compose.project')!=b.PREFIX):
        raise ValueError('installed qualification drift')
    return proof


def recover_network_default(config,state,task,payload,intent,startup,info,tool_calls,acp_events):
    """One changed-policy CTO planning round, never replay the failed transport."""
    try:import worker_creation_intent as workers
    except ImportError:from broker import worker_creation_intent as workers
    if (not config.get('bootstrap_failure') or config.get('bootstrap_policy_revision')
            or state.get('bootstrap_policy_recovery') or state.get('stage')!='blocked'
            or state.get('category')!='surgical_failure_diagnosis_rejected'
            or state.get('executor') or state.get('binding_recovery')
            or state.get('peer_wakeup') or state.get('cto_decision')
            or task.get('status')!='failed' or task.get('agent_id')!=config['cto']
            or task.get('issue_id')!=config['issue_id'] or task.get('wakeup_id')!=state.get('cto_wakeup')
            or tool_calls!=0 or acp_events!=0
            or intent.get('stage')!='ownership_or_policy_conflict'
            or startup.get('stage')!='failed' or startup.get('category')!='startup_broker_internal'
            or payload.get('NetworkDisabled') is not False or not info
            or 'NetworkDisabled' in info.get('Config',{})):
        raise ValueError('one authenticated omitted-false pre-ACP CTO incident required')
    observed,_=workers.observe(payload,{'stage':'start_acknowledged'},info,'failed',0,time.time())
    if observed['stage']!='late_start_observed':raise ValueError('complete original worker policy must match')
    receipt=dict(operation='docker_omitted_false_CTO_recovery_v1',previous_state=state,
        failed_task=task['id'],failed_wakeup=task['wakeup_id'],container_id=info['Id'],
        payload_sha256=observed['fact']['payload_sha256'],previous_startup=startup,previous_creation_intent=intent,
        tool_calls=0,acp_events=0,transport_replayed=False,author_retry_authorized=False,delivery_approval=False)
    changed={**config,'bootstrap_policy_revision':1}
    new={k:v for k,v in state.items() if not k.startswith(('cto_','peer_'))
         and k not in ('at','intent_at','category','error_type','required_action')}
    new.update(stage='bootstrap_retirement_pending',bootstrap_policy_recovery=receipt,
        required_action='retire_exact_terminal_CTO_worker_before_fresh_planning',
        author_retry_authorized=False,delivery_approval=False)
    return changed,new


def arm_network_default_recovery(b,source):
    """Maintenance-only bootstrap: no worker endpoint and no native wakeup here."""
    _,admission,_,jobs,_,native=modules()
    with b.LOCK:
        with b.db() as con:
            row=con.execute('SELECT config,state FROM calibration_failure_plans WHERE source_task=?',(source,)).fetchone()
            if not row:raise ValueError('actual incident required')
            config,state=map(json.loads,row)
            if config.get('bootstrap_policy_revision'):return state
            installed_line_qualification(b,con)
            route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(config['issue_id'],)).fetchone()[0])
            if (not route['enabled'] or route['contract_sha256']!=config['contract_sha256']
                    or any(config[k]!=route[v] for k,v in (('author','author'),('cto','cto'),('peer','techlead')))
                    or len({config[k] for k in ('author','cto','peer')})!=3
                    or con.execute('SELECT 1 FROM test_first_red WHERE issue_id=?',(config['issue_id'],)).fetchone()):
                raise ValueError('unchanged pre-Red independent route required')
        settings=json.loads((b.STATE/'native.json').read_text())
        runs=native.issue_task_runs(settings,config['issue_id'])
        tasks=[t for t in runs if t.get('wakeup_id')==state.get('cto_wakeup')]
        if len(tasks)!=1 or any(t['status'] in ('queued','dispatched','running') for t in runs):
            raise ValueError('one terminal CTO task and idle native issue required')
        task=tasks[0]
        current_cto=[t for t in runs if t.get('agent_id')==config['cto']]
        authors=[t for t in runs if t.get('agent_id')==config['author']]
        if (not current_cto or max(current_cto,key=lambda t:(t.get('created_at') or '',t['id']))['id']!=task['id']
                or not authors or max(authors,key=lambda t:(t.get('created_at') or '',t['id']))['id']!=source):
            raise ValueError('recovery superseded by a newer execution')
        messages=native.task_messages(settings,task['id'])
        tools=sum(m.get('type') in ('tool_use','tool_result') for m in messages)
        with b.db() as con:
            records=con.execute('SELECT n.request_id,l.name,l.status,g.used,g.mode FROM native_bindings n '
                'JOIN leases l USING(request_id) JOIN grants g USING(request_id) '
                'WHERE n.task_id=? AND n.agent_id=? AND n.issue_id=?',
                (task['id'],config['cto'],config['issue_id'])).fetchall()
            if len(records)!=1 or records[0][3]!=1 or records[0][4]!='planning':
                raise ValueError('exact consumed planning capability required')
            request,name,_,_,_=records[0]
            if con.execute("SELECT 1 FROM leases WHERE request_id!=? AND status IN ('creating','starting','running','active','closing')",(request,)).fetchone():
                raise ValueError('other active lease')
            acp=con.execute('SELECT count(*) FROM acp_events WHERE request_id=?',(request,)).fetchone()[0]
            payload,intent=map(json.loads,con.execute('SELECT payload,state FROM worker_creation_intents WHERE request_id=?',(request,)).fetchone())
            startup=json.loads(con.execute('SELECT state FROM acp_startups WHERE request_id=?',(request,)).fetchone()[0])
            errors=[tuple(r) for r in con.execute('SELECT operation,category FROM broker_errors WHERE request_id=?',(request,))]
            if ('acp_startup','startup_broker_internal') not in errors or any(r[0]=='transport_start' for r in errors):
                raise ValueError('actual pre-transport startup failure required')
        rec=state['probe'];frozen=b.docker('GET','/containers/'+rec['container_id']+'/json')
        jobs.verify_job(frozen,rec['payload'])
        if frozen['State']['Status']!='exited' or frozen['State']['Running'] or frozen['State']['ExitCode']!=0:
            raise ValueError('completed immutable preservation job required')
        raw=b.docker_stdout(frozen['Id'],include_stderr=False,limit=4096)
        if hashlib.sha256(raw.encode()).hexdigest()!=rec['receipt_sha256'] or json.loads(raw)!=rec['proof']:
            raise ValueError('immutable preservation receipt drift')
        admission.validate_preservation(rec['proof'],config)
        info=b.docker('GET','/containers/'+name+'/json')
        changed,new=recover_network_default(config,state,task,payload,intent,startup,info,tools,acp)
        labels=payload['Labels']
        if (payload['Image']!=b.IMAGE or labels.get('delivery-kit.owner')!=b.OWNER
                or labels.get('delivery-kit.request')!=request):raise ValueError('exact qualified owned worker required')
        new['bootstrap_policy_recovery'].update(request_id=request,name=name)
        with b.db() as con:
            if tuple(con.execute('SELECT config,state FROM calibration_failure_plans WHERE source_task=?',(source,)).fetchone())!=tuple(row):
                raise ValueError('incident changed during recovery')
            con.execute('UPDATE calibration_failure_plans SET config=?,state=? WHERE source_task=?',
                (json.dumps(changed,sort_keys=True),json.dumps(new,sort_keys=True),source))
            con.execute("UPDATE leases SET status='closing' WHERE request_id=?",(request,))
        return new


def reconcile(config,state,identity,experiment):
    """One changed-evidence planning round; retain the original decisions verbatim."""
    try:import calibration_failure_plan as plans
    except ImportError:from broker import calibration_failure_plan as plans
    if (config.get('evidence_revision') or state.get('evidence_reconciliation')
            or state['stage']!='plan_qualified' or not config.get('execution_failure')
            or state.get('executor') or state.get('binding_recovery')):
        raise ValueError('one unconsumed diagnostic-only evidence reconciliation required')
    proof=experiment['proof'];plans.validate_experiment(proof,identity)
    held=state['probe']['proof']
    if (experiment['stage']!='complete' or identity['source_task']!=config['predecessor_plan']
            or identity['issue_id']!=config['issue_id']
            or held.get('all_files_unchanged') is not True
            or config['manifest_sha256']!=proof['original_manifest_sha256']
            or held['manifest_sha256']!=proof['original_manifest_sha256']
            or config['diagnostic']['test_sha256']!=proof['original_test_sha256']
            or held['test_sha256']!=proof['original_test_sha256']):
        raise ValueError('same immutable submission and executed experiment required')
    changed={**config,'evidence_revision':1,'empirical_failure':dict(phase=proof['original']['phase'],
        failed_methods=proof['original']['facts']['positive']['failed_methods'])}
    receipt=dict(operation='executed_failure_context_reconciliation_v1',previous_config=config,previous_state=state,
        experiment_receipt_sha256=experiment['receipt_sha256'],original_manifest_sha256=config['manifest_sha256'],
        decisions_replayed=False,author_retry_authorized=False,delivery_approval=False)
    new={k:v for k,v in state.items() if not k.startswith(('cto_','peer_')) and k not in ('at','intent_at','required_action')}
    new.update(stage='cto_pending',evidence_reconciliation=receipt,author_retry_authorized=False,delivery_approval=False)
    _,_,lane,_,_,_=modules()
    lane.instruction(changed,new)
    return changed,new


def arm_evidence_reconciliation(b,source):
    """Controller migration only; no worker endpoint, arbitrary evidence or retry."""
    executor,_,lane,jobs,handoffs,native=modules()
    try:import handoff_runtime
    except ImportError:from broker import handoff_runtime
    with b.LOCK:
        with b.db() as con:
            row=con.execute('SELECT config,state FROM calibration_failure_plans WHERE source_task=?',(source,)).fetchone()
            if not row:raise ValueError('actual diagnostic plan required')
            config,state=map(json.loads,row)
            if config.get('evidence_revision'):return state
            route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(config['issue_id'],)).fetchone()[0])
            registered=con.execute('SELECT receipt FROM template_registry_qualifications WHERE worker_image=?',(b.IMAGE,)).fetchone()
            if not registered:raise ValueError('qualified installed registry required')
            qualification=json.loads(registered[0]);executor.validate_qualification(qualification)
            if qualification['worker_image']!=b.IMAGE:raise ValueError('installed qualification drift')
            identity,experiment=map(json.loads,con.execute('SELECT identity,state FROM observation_hypothesis_experiments WHERE source_task=?',
                (config['predecessor_plan'],)).fetchone())
            if (not route['enabled'] or route['contract_sha256']!=config['contract_sha256']
                    or any(config[k]!=route[v] for k,v in (('author','author'),('cto','cto'),('peer','techlead')))
                    or len({config[k] for k in ('author','cto','peer')})!=3
                    or con.execute('SELECT 1 FROM test_first_red WHERE issue_id=?',(config['issue_id'],)).fetchone()
                    or con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','active','closing')").fetchone()):
                raise ValueError('idle unchanged pre-Red diagnostic route required')
        proxy=b.docker('GET','/containers/'+b.PREFIX+'-model-proxy-1/json')
        if not proxy or proxy['Image']!=qualification['proxy_image'] or not proxy['State']['Running']:
            raise ValueError('qualified installed proxy required')
        settings=json.loads((b.STATE/'native.json').read_text());fx=handoff_runtime.Effects(b,settings)
        runs=native.issue_task_runs(settings,config['issue_id'])
        authors=[r for r in runs if r.get('agent_id')==config['author']]
        if (not authors or max(authors,key=lambda r:(r.get('created_at') or '',r['id']))['id']!=source
                or next(r for r in authors if r['id']==source)['status']!='failed'
                or any(r['status'] in ('queued','dispatched','running') for r in runs)):
            raise ValueError('latest failed author and idle tasks required')
        for role in ('cto','peer'):
            task=native.task_record(settings,state[role+'_task'],config[role]);reads=fx.read_evidence(task)
            if (task['status']!='completed' or task.get('issue_id')!=config['issue_id']
                    or task.get('wakeup_id')!=state[role+'_wakeup'] or fx.decision(task)!=state[role+'_decision']
                    or 'DELIVERY_EXECUTED_FAILURES_V1' in (task.get('handoff_note') or '')
                    or any(reads.get(p,{}).get('lines',0)<=0 or reads[p]['lines']!=reads[p].get('total_lines') for p in config['paths'])):
                raise ValueError('actual completed old-context independent reads required')
        info=b.docker('GET','/containers/'+experiment['container_id']+'/json');jobs.verify_job(info,identity['payload'])
        if info['State']['Running'] or info['State']['Status']!='exited' or info['State']['ExitCode']!=0:
            raise ValueError('actual completed immutable experiment required')
        raw=b.docker_stdout(info['Id'],include_stderr=False,limit=32768)
        if hashlib.sha256(raw.encode()).hexdigest()!=experiment['receipt_sha256'] or json.loads(raw)!=experiment['proof']:
            raise ValueError('immutable experiment receipt drift')
        rec=state['probe'];info=b.docker('GET','/containers/'+rec['container_id']+'/json');jobs.verify_job(info,rec['payload'])
        if info['State']['Running'] or info['State']['Status']!='exited' or info['State']['ExitCode']!=0:
            raise ValueError('actual completed preservation required')
        raw=b.docker_stdout(info['Id'],include_stderr=False,limit=4096)
        if hashlib.sha256(raw.encode()).hexdigest()!=rec['receipt_sha256'] or json.loads(raw)!=rec['proof']:
            raise ValueError('immutable preservation receipt drift')
        changed,new=reconcile(config,state,identity,experiment)
        with b.db() as con:
            current=con.execute('SELECT config,state FROM calibration_failure_plans WHERE source_task=?',(source,)).fetchone()
            if tuple(current)!=tuple(row):raise ValueError('diagnostic changed during reconciliation')
            con.execute('UPDATE calibration_failure_plans SET config=?,state=? WHERE source_task=?',
                (json.dumps(changed,sort_keys=True),json.dumps(new,sort_keys=True),source))
            held=handoffs.load(con,source);data=json.loads(held['data'])
            data.update(required_action='reconcile_executed_failure_evidence_not_replay_previous_decisions',
                calibration_failure_plan=dict(source_task=source,manifest_sha256=changed['manifest_sha256'],state=new))
            handoffs.save(con,source,changed['issue_id'],'calibration_failure_plan',changed['cto'],data,time.time())
        return new


def handle(b,route,runs,source,prior,effects):
    executor,admission,lane,jobs,handoffs,native=modules()
    key=source['id'];issue=route['issue_id']
    with b.db() as con:
        existing=con.execute('SELECT config,state FROM calibration_failure_plans WHERE source_task=?',(key,)).fetchone()
        if existing:
            config,state=map(json.loads,existing)
            if not config.get('execution_failure'):return False
        else:
            rows=con.execute('SELECT source_task,config,state FROM calibration_failure_plans').fetchall()
            parents=[(p,json.loads(c),json.loads(s)) for p,c,s in rows if json.loads(c)['issue_id']==issue
                and (executor.selected_executor(json.loads(s)) or {}).get('task_id')==key
                and (executor.selected_executor(json.loads(s)) or {}).get('status')=='blocked']
            if not parents:return False
            if len(parents)!=1:raise ValueError('one exact failed executor predecessor required')
            parent,previous,held=parents[0]
            if (source.get('status')!='failed' or source.get('agent_id')!=previous['author']
                    or source.get('wakeup_id')!=executor.selected_executor(held).get('wakeup_id')
                    or any(t['status'] in ('queued','dispatched','running') for t in runs)
                    or con.execute('SELECT 1 FROM test_first_red WHERE issue_id=?',(issue,)).fetchone()
                    or con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','active','closing')").fetchone()):
                return False
            authors=[t for t in runs if t.get('agent_id')==previous['author']]
            if not authors or max(authors,key=lambda t:(t.get('created_at') or '',t['id']))['id']!=key:return False
            bindings=con.execute('SELECT l.status FROM native_bindings n JOIN leases l USING(request_id) '
                'WHERE n.task_id=? AND n.issue_id=? AND n.agent_id=?',(key,issue,previous['author'])).fetchall()
            if len(bindings)!=1 or bindings[0][0] not in ('closed','failed'):return False
            if (previous['contract_sha256']!=route['contract_sha256']
                    or any(previous[k]!=route[v] for k,v in (('author','author'),('cto','cto'),('peer','techlead')))
                    or len({previous[k] for k in ('author','cto','peer')})!=3):
                raise ValueError('unchanged distinct diagnostic roles required')
            messages=native.task_messages(effects.settings,key)
            bootstrap=bindings[0][0]=='failed'
            evidence=bootstrap_evidence(b,con,key,issue,previous['author'],held,messages) if bootstrap else denials(messages)
            qualification=installed_line_qualification(b,con) if bootstrap else None
            frozen=b.snapshot_submission({'task_id':key},diagnostic=True)
            volume=frozen['volume']
            for name,task in ((previous['volume'],parent),(volume,key)):
                labels=b.docker('GET','/volumes/'+name).get('Labels',{})
                if (labels.get('delivery-kit.owner')!=b.OWNER or labels.get('delivery-kit.source-task')!=task
                        or labels.get('delivery-kit.diagnostic-only')!='true'):
                    raise ValueError('owned diagnostic snapshots required')
            payload=jobs.payload(b,key,volume,previous['manifest_sha256'])
            payload['Cmd']=['/template_preservation_probe.py','/previous','/delivery']
            payload['HostConfig']['Mounts'].append(dict(Type='volume',Source=previous['volume'],Target='/previous',ReadOnly=True))
            payload['Labels']['delivery-kit.purpose']='template-failure-diagnosis'
            config={**previous,'source_task':key,'volume':volume,'diagnosis_only':True,
                'execution_failure':evidence,'predecessor_plan':parent}
            if bootstrap:
                if not previous.get('line_recipe_revision'):raise ValueError('qualified bounded line proposal required')
                config.update(bootstrap_failure=evidence,line_qualification_sha256=executor.digest(qualification))
            state=dict(stage='preservation_pending',probe=dict(payload=payload,
                name=b.PREFIX+'-template-failure-diagnosis-'+key),previous_executor_sha256=executor.digest(held),
                author_retry_authorized=False,delivery_approval=False)
            con.execute('INSERT INTO calibration_failure_plans VALUES(?,?,?)',
                        (key,json.dumps(config,sort_keys=True),json.dumps(state,sort_keys=True)))
    if (not route.get('enabled') or config['contract_sha256']!=route['contract_sha256']
            or any(config[k]!=route[v] for k,v in (('author','author'),('cto','cto'),('peer','techlead')))):
        raise ValueError('diagnostic route drift')
    def persist(new):
        with b.db() as con:
            current=handoffs.load(con,key);data=json.loads(current['data']) if current else {}
            con.execute('UPDATE calibration_failure_plans SET state=? WHERE source_task=?',
                        (json.dumps(new,sort_keys=True),key))
            # This is a new incident plan, not a reset/mirror of its predecessor.
            data.pop('calibration_failure_plan_source',None)
            data.update(calibration_failure_plan=dict(source_task=key,manifest_sha256=config['manifest_sha256'],state=new),
                required_action=new.get('required_action','surgical_failure_diagnosis:'+new['stage']))
            owner=config['peer'] if new['stage'].startswith('peer') else config['cto']
            if new.get('executor',{}).get('status') in ('ready','intent','waiting','author_completed_awaiting_gates'):
                owner=config['author']
            handoffs.save(con,key,issue,'calibration_failure_plan',owner,data,time.time())
    try:
        if state['stage']=='bootstrap_retirement_pending':
            recovery=state['bootstrap_policy_recovery']
            # remove_owned persists the exact deletion intent; repeated calls
            # observe its outcome instead of repeating a DELETE.
            try:b.remove_owned(recovery['name'],recovery['request_id'])
            except b.DockerOperationTimeout:return True
            if b.docker('GET','/containers/'+recovery['name']+'/json') is not None:return True
            with b.db() as con:
                con.execute("UPDATE leases SET status='failed' WHERE request_id=?",(recovery['request_id'],))
            persist({**state,'stage':'cto_pending','required_action':'fresh_CTO_planning_after_verified_policy_correction'})
            return True
        repaired=lane.recover_technical_escalation(config,state,runs,effects)
        if repaired:
            persist(repaired)
            return True
        if state['stage'].startswith('preservation'):
            state=probe(b,config,state,persist)
        elif state.get('executor'):
            executor.advance(config,state,effects,persist)
        else:
            state=lane.advance(config,state,runs,effects,persist)
            if config.get('line_recipe_revision') and state['stage']=='plan_qualified':
                admitted=executor.admit_line_plan(b,config,state)
                if admitted:persist({**state,'executor':admitted,'required_action':'dispatch_independently_sponsored_V6_author'})
    except (ValueError,TypeError,KeyError) as error:
        persist({**state,'stage':'blocked','category':'surgical_failure_diagnosis_rejected',
            'error_type':type(error).__name__,'required_action':'CTO_inspect_exact_diagnostic_failure',
            'author_retry_authorized':False,'delivery_approval':False})
    return True


def probe(b,config,state,persist):
    _,admission,_,jobs,_,_=modules();rec=state['probe'];first=state['stage']=='preservation_pending'
    if first:
        state={**state,'stage':'preservation_intent','intent_at':time.time()};persist(state)
    info=b.docker('GET','/containers/'+rec['name']+'/json')
    if not info:
        if not first:
            if time.time()-state['intent_at']>=1800:
                state={**state,'stage':'blocked','required_action':'observe_uncertain_diagnostic_probe_no_recreate'};persist(state)
            return state
        b.docker('POST','/containers/create?name='+rec['name'],rec['payload'])
        info=b.docker('GET','/containers/'+rec['name']+'/json')
        if not info:return state
    jobs.verify_job(info,rec['payload'])
    if info['State']['Status']=='created':b.docker('POST','/containers/'+info['Id']+'/start');return state
    if info['State']['Running']:return state
    if info['State']['Status']!='exited' or info['State']['ExitCode']!=0:
        raise ValueError('successful fixed read-only preservation required')
    raw=b.docker_stdout(info['Id'],include_stderr=False,limit=4096);proof=json.loads(raw)
    admission.validate_preservation(proof,config)
    if (type(proof.get('test_bytes')) is not int or not 0<proof['test_bytes']<=32768
            or proof.get('file_limit_bytes')!=32768 or proof.get('available_growth_bytes')!=32768-proof['test_bytes']):
        raise ValueError('measured immutable file byte budget required')
    state={**state,'stage':'cto_pending','probe':{**rec,'container_id':info['Id'],
        'receipt_sha256':hashlib.sha256(raw.encode()).hexdigest(),'proof':proof}}
    persist(state);return state
