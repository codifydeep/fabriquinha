"""One changed binding-admission recovery; preserve the failed executor verbatim.

Controller-only registration, a fixed durable read-only job, then normal dispatch.
Neither a new image nor a textual success claim can qualify this path alone.
"""
import json,time


def modules():
    try:import template_author_executor as executor,harness_qualification as jobs,native,handoff_runtime,handoffs
    except ImportError:from broker import template_author_executor as executor,harness_qualification as jobs,native,handoff_runtime,handoffs
    return executor,jobs,native,handoff_runtime,handoffs


def arm(b,source,qualification):
    executor,jobs,native,runtime,handoffs=modules();executor.validate_qualification(qualification)
    with b.LOCK:
        with b.db() as con:
            row=con.execute('SELECT config,state FROM calibration_failure_plans WHERE source_task=?',(source,)).fetchone()
            if not row:raise ValueError('original immutable sponsored plan required')
            config,state=map(json.loads,row)
            if state.get('binding_recovery'):
                if state['binding_recovery']['qualification']!=qualification:raise ValueError('binding recovery already consumed')
                return state['binding_recovery']
            old=state.get('executor',{})
            route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(config['issue_id'],)).fetchone()[0])
            proof=con.execute('SELECT receipt FROM template_registry_qualifications WHERE worker_image=?',(b.IMAGE,)).fetchone()
            if (old.get('status')!='blocked' or not old.get('task_id') or state['stage']!='plan_qualified'
                    or not route['enabled'] or route['contract_sha256']!=config['contract_sha256']
                    or any(config[k]!=route[v] for k,v in (('author','author'),('cto','cto'),('peer','techlead')))
                    or len({config[k] for k in ('author','cto','peer')})!=3
                    or qualification['worker_image']!=b.IMAGE or old['worker_image']==b.IMAGE
                    or not proof or json.loads(proof[0])!=qualification
                    or con.execute('SELECT 1 FROM test_first_red WHERE issue_id=?',(config['issue_id'],)).fetchone()
                    or con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','active','closing')").fetchone()):
                raise ValueError('idle qualified changed native-binding admission required')
            closed=con.execute('SELECT l.status FROM native_bindings n JOIN leases l USING(request_id) WHERE n.task_id=? AND n.agent_id=? AND n.issue_id=?',
                               (old['task_id'],config['author'],config['issue_id'])).fetchall()
            if len(closed)!=1 or closed[0][0]!='closed':raise ValueError('exact closed failed executor required')
        proxy=b.docker('GET','/containers/'+b.PREFIX+'-model-proxy-1/json')
        if (not proxy or proxy['Image']!=qualification['proxy_image'] or not proxy['State']['Running']
                or proxy['Config']['Labels'].get('com.docker.compose.project')!=b.PREFIX):
            raise ValueError('qualified installed proxy required')
        settings=json.loads((b.STATE/'native.json').read_text());fx=runtime.Effects(b,settings)
        runs=native.issue_task_runs(settings,config['issue_id']);authors=[t for t in runs if t.get('agent_id')==config['author']]
        task=native.task_record(settings,old['task_id'],config['author'])
        if (not authors or max(authors,key=lambda t:(t.get('created_at') or '',t['id']))['id']!=task['id']
                or task['status']!='failed' or task.get('wakeup_id')!=old['wakeup_id']
                or task.get('issue_id')!=config['issue_id'] or any(t['status'] in ('queued','dispatched','running') for t in runs)):
            raise ValueError('latest idle failed binding execution required')
        validate_rejections(native.task_messages(settings,task['id']))
        for role in ('cto','peer'):
            sponsor=native.task_record(settings,state[role+'_task'],config[role]);reads=fx.read_evidence(sponsor)
            if (sponsor['status']!='completed' or sponsor.get('issue_id')!=config['issue_id']
                    or sponsor.get('wakeup_id')!=state[role+'_wakeup'] or fx.decision(sponsor)!=state[role+'_decision']
                    or any(reads.get(p,{}).get('lines',0)<=0 or reads[p]['lines']!=reads[p].get('total_lines') for p in config['paths'])):
                raise ValueError('unchanged actual independent sponsorship required')
        frozen=b.snapshot_submission({'task_id':task['id']},diagnostic=True)
        for volume,key in ((config['volume'],source),(frozen['volume'],task['id'])):
            labels=b.docker('GET','/volumes/'+volume).get('Labels',{})
            if (labels.get('delivery-kit.owner')!=b.OWNER or labels.get('delivery-kit.source-task')!=key
                    or labels.get('delivery-kit.diagnostic-only')!='true'):
                raise ValueError('owned immutable failed snapshots required')
        payload=jobs.payload(b,task['id'],frozen['volume'],config['manifest_sha256'])
        payload['Cmd']=['/template_preservation_probe.py','/previous','/delivery']
        payload['HostConfig']['Mounts'].append(dict(Type='volume',Source=config['volume'],Target='/previous',ReadOnly=True))
        payload['Labels']['delivery-kit.purpose']='template-binding-preservation'
        recovery=dict(stage='probe_pending',source_task=task['id'],qualification=qualification,
            prior_executor_sha256=executor.digest(old),payload=payload,
            name=b.PREFIX+'-template-binding-preservation-'+task['id'],attempt_limit=1,
            delivery_approval=False,author_retry_authorized=False)
        with b.db() as con:
            current=con.execute('SELECT config,state FROM calibration_failure_plans WHERE source_task=?',(source,)).fetchone()
            if tuple(current)!=tuple(row):raise ValueError('immutable proposal changed during admission')
            state['binding_recovery']=recovery
            con.execute('UPDATE calibration_failure_plans SET state=? WHERE source_task=?',(json.dumps(state,sort_keys=True),source))
            held=handoffs.load(con,task['id']);data=json.loads(held['data']) if held else {}
            data.update(calibration_failure_plan_source=source,required_action='verify_unchanged_snapshot_before_binding_recovery')
            handoffs.save(con,task['id'],config['issue_id'],'calibration_failure_plan',config['cto'],data,time.time())
        return recovery


def validate_rejections(messages):
    calls=[m for m in messages if m.get('type')=='tool_use'];results=[m for m in messages if m.get('type')=='tool_result' and m.get('tool')=='patch']
    patches=[m for m in calls if m.get('tool')=='patch'];ids={m.get('call_id') for m in patches}
    if (not calls or any(m.get('tool') not in ('read_file','patch') for m in calls)
            or sum(m.get('tool')=='read_file' for m in calls)<1
            or len(patches)!=2 or len(results)!=2 or None in ids or len(ids)!=2
            or {m.get('call_id') for m in results}!=ids or any(m.get('output_truncated') for m in results)
            or any(m.get('output')!='patch failed for /workspace/tests/test_service_mode_indicator.py: surgical_edit_rejected:operation_forbidden:use_surgical_tool_only' for m in results)):
        raise ValueError('actual two denied generic patches and read-only observations required')


def advance(b,config,state,persist):
    executor,jobs,_,_,_=modules();rec=state['binding_recovery'];first=rec['stage']=='probe_pending'
    if first:
        rec={**rec,'stage':'probe_intent','intent_at':time.time()};state={**state,'binding_recovery':rec};persist(state)
    info=b.docker('GET','/containers/'+rec['name']+'/json')
    if not info:
        if not first:
            if time.time()-rec['intent_at']>=1800:
                rec={**rec,'stage':'blocked','required_action':'observe_uncertain_preservation_job_no_recreate'}
                state={**state,'binding_recovery':rec};persist(state)
            return state
        b.docker('POST','/containers/create?name='+rec['name'],rec['payload'])
        info=b.docker('GET','/containers/'+rec['name']+'/json')
        if not info:return state
    jobs.verify_job(info,rec['payload'])
    if info['State']['Status']=='created':
        b.docker('POST','/containers/'+info['Id']+'/start');return state
    if info['State']['Running']:
        state={**state,'binding_recovery':{**rec,'stage':'probe_running','container_id':info['Id']}};persist(state);return state
    if info['State']['Status']!='exited' or info['State']['ExitCode']!=0:
        state={**state,'binding_recovery':{**rec,'stage':'blocked','required_action':'CTO_inspect_preservation_job'}};persist(state);return state
    raw=b.docker_stdout(info['Id'],include_stderr=False,limit=4096);proof=json.loads(raw)
    validate_preservation(proof,config)
    contract=dict(previous_executor_sha256=rec['prior_executor_sha256'],failed_task=rec['source_task'],
        operation='changed_native_binding_admission_v1',qualification_sha256=executor.digest(rec['qualification']),
        preservation_sha256=executor.digest(proof),unchanged_delivery_contract=config['contract_sha256'],
        unchanged_criteria=config['criteria'],author=config['author'],cto_task=state['cto_task'],peer_task=state['peer_task'])
    value=dict(status='ready',contract=contract,contract_sha256=executor.digest(contract),
        qualification=rec['qualification'],worker_image=rec['qualification']['worker_image'],
        surgical=state['executor']['surgical'],attempt_limit=1,delivery_approval=False)
    rec={**rec,'stage':'executor_ready','container_id':info['Id'],'receipt_sha256':executor.digest(proof),
         'preservation':proof,'executor':value,'author_retry_authorized':False}
    state={**state,'binding_recovery':rec}
    if len(executor.note(config,state))+100>4000:raise ValueError('bounded binding correction note required')
    persist(state);return state


def validate_preservation(proof,config):
    if (proof.get('operation')!='template_admission_preservation_v1' or proof.get('status')!='passed'
            or proof.get('manifest_sha256')!=config['manifest_sha256']
            or proof.get('test_sha256')!=config['diagnostic']['test_sha256']
            or type(proof.get('files')) is not int or proof['files']<1
            or proof.get('all_files_unchanged') is not True or proof.get('delivery_approval') is not False):
        raise ValueError('actual entire frozen submission unchanged proof required')
