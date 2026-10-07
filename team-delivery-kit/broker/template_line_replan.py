"""Pure changed-evidence planner transition; no I/O, edits or worker admission."""
import hashlib,json,re,time
try:from template_author_executor import validate_line_qualification,digest
except ImportError:from broker.template_author_executor import validate_line_qualification,digest


def prepare(config,state,proof,qualification):
    """Consume only an executed fixed-recipe proof for the exact held snapshot.

    The controller must authenticate the job, image, ownership and durable receipt
    before calling. The returned state requires NEW independent planner decisions.
    Neither the proof nor this function grants implementation or delivery approval.
    """
    validate_line_qualification(qualification)
    if (config.get('line_recipe_revision') or state.get('line_recipe_reconciliation')
            or state.get('stage')!='blocked' or state.get('category')!='calibration_technical_impediment'
            or not config.get('diagnosis_only') or not config.get('execution_failure')
            or state.get('executor') or state.get('binding_recovery')
            or state.get('cto_decision',{}).get('action')!='escalate_cto'
            or state.get('owner')!=config.get('cto')
            or len({config[k] for k in ('author','cto','peer')})!=3):
        raise ValueError('one exact technical hold without an executor required')
    preserved=state.get('probe',{}).get('proof',{})
    if (proof.get('operation')!='template_line_recipe_feasibility_v1' or proof.get('status')!='prepared'
            or proof.get('original_manifest_sha256')!=config['manifest_sha256']
            or proof.get('original_test_sha256')!=config['diagnostic']['test_sha256']
            or any(proof.get(k) is not True for k in ('exact_experiment_variant','inputs_unchanged','diagnostic_only'))
            or any(proof.get(k) is not False for k in ('valid_red_green_receipt','author_retry_authorized','delivery_approval'))
            or preserved.get('all_files_unchanged') is not True
            or preserved.get('manifest_sha256')!=proof['original_manifest_sha256']
            or preserved.get('test_sha256')!=proof['original_test_sha256']
            or not re.fullmatch(r'[a-f0-9]{64}',str(proof.get('variant_test_sha256','')))
            or proof['variant_test_sha256']==proof['original_test_sha256']):
        raise ValueError('same preserved submission and nonapproving fixed experiment required')
    for key in ('file_bytes','proposed_bytes','growth_bytes','file_limit_bytes','available_growth_bytes'):
        if type(proof.get(key)) is not int:raise ValueError('measured UTF-8 budget required')
    if (not 0<proof['file_bytes']<=32768 or not 0<proof['proposed_bytes']<=32768
            or proof['file_limit_bytes']!=32768
            or proof['file_bytes']!=preserved.get('test_bytes')
            or proof['available_growth_bytes']!=32768-proof['file_bytes']
            or proof['growth_bytes']!=proof['proposed_bytes']-proof['file_bytes']):
        raise ValueError('unchanged size limit and exact byte measurement required')
    try:from surgical_test_edit import validate_line_envelope
    except ImportError:raise ValueError('qualified line envelope validator required')
    validate_line_envelope(proof['recipe'],proof['original_test_sha256'])
    if proof['recipe']['expected_sha256']!=proof['original_test_sha256']:
        raise ValueError('recipe must bind the original held file')
    changed={**config,'line_recipe_revision':1,'line_recipe':proof,
        'line_qualification_sha256':digest(qualification)}
    new={k:v for k,v in state.items() if not k.startswith(('cto_','peer_'))
         and k not in ('category','owner','required_action','at','intent_at','error_type')}
    new.update(stage='cto_pending',line_recipe_reconciliation=dict(
        operation='template_line_changed_evidence_replan_v1',previous_config=config,previous_state=state,
        proof_sha256=digest(proof),qualification_sha256=digest(qualification),
        decisions_replayed=False,author_retry_authorized=False,delivery_approval=False),
        author_retry_authorized=False,delivery_approval=False)
    return changed,new


def job_payload(b,config,variant_sha):
    """Fixed read-only experiment; the caller cannot supply a command."""
    try:import harness_qualification as jobs
    except ImportError:from broker import harness_qualification as jobs
    if not re.fullmatch(r'[a-f0-9]{64}',str(variant_sha)):
        raise ValueError('executed variant identity required')
    payload=jobs.payload(b,config['source_task'],config['volume'],config['manifest_sha256'])
    payload['Cmd']=['/template_line_recipe_probe.py','/delivery',config['manifest_sha256'],variant_sha]
    payload['Labels']['delivery-kit.purpose']='template-line-feasibility'
    return payload


def arm(b,source,container_id):
    """Controller-only migration backed by actual jobs and native decisions.

    Reopens planning only. It never wakes an author, changes a file, resets an
    executor, manufactures Red or accepts a worker's claim that a probe ran.
    """
    if not re.fullmatch(r'[a-f0-9]{64}',str(container_id)):
        raise ValueError('exact completed experiment container required')
    try:import native,handoff_runtime,calibration_failure_plan as plans,harness_qualification as jobs,handoffs
    except ImportError:from broker import native,handoff_runtime,calibration_failure_plan as plans,harness_qualification as jobs,handoffs
    with b.LOCK:
        with b.db() as con:
            row=con.execute('SELECT config,state FROM calibration_failure_plans WHERE source_task=?',(source,)).fetchone()
            if not row:raise ValueError('preserved technical hold required')
            config,state=map(json.loads,row)
            if config.get('line_recipe_revision'):
                if state['line_recipe_reconciliation'].get('container_id')!=container_id:
                    raise ValueError('one immutable line replan experiment required')
                return state
            route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(config['issue_id'],)).fetchone()[0])
            qualification_row=con.execute('SELECT receipt FROM template_registry_qualifications WHERE worker_image=?',(b.IMAGE,)).fetchone()
            if not qualification_row:raise ValueError('installed V6 image qualification required')
            qualification=json.loads(qualification_row[0]);validate_line_qualification(qualification)
            if (qualification['worker_image']!=b.IMAGE or not route['enabled']
                    or route['contract_sha256']!=config['contract_sha256']
                    or any(config[k]!=route[v] for k,v in (('author','author'),('cto','cto'),('peer','techlead')))
                    or con.execute('SELECT 1 FROM test_first_red WHERE issue_id=?',(config['issue_id'],)).fetchone()
                    or con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','active','closing')").fetchone()):
                raise ValueError('idle unchanged exact pre-Red route required')
            experiment_row=con.execute('SELECT identity,state FROM observation_hypothesis_experiments WHERE source_task=?',(config['predecessor_plan'],)).fetchone()
            if not experiment_row:raise ValueError('executed predecessor hypothesis required')
            identity,experiment=map(json.loads,experiment_row)
        proxy=b.docker('GET','/containers/'+b.PREFIX+'-model-proxy-1/json')
        if (not proxy or proxy['Image']!=qualification['proxy_image'] or not proxy['State']['Running']
                or proxy['Config']['Labels'].get('com.docker.compose.project')!=b.PREFIX):
            raise ValueError('exact installed qualified proxy required')
        settings=json.loads((b.STATE/'native.json').read_text());fx=handoff_runtime.Effects(b,settings)
        runs=native.issue_task_runs(settings,config['issue_id'])
        authors=[r for r in runs if r.get('agent_id')==config['author']]
        if (not authors or max(authors,key=lambda r:(r.get('created_at') or '',r['id']))['id']!=source
                or next(r for r in authors if r['id']==source)['status']!='failed'
                or any(r['status'] in ('queued','dispatched','running') for r in runs)):
            raise ValueError('latest failed author and idle native tasks required')
        task=native.task_record(settings,state['cto_task'],config['cto']);reads=fx.read_evidence(task)
        if (task['status']!='completed' or task.get('agent_id')!=config['cto'] or task.get('issue_id')!=config['issue_id']
                or task.get('wakeup_id')!=state['cto_wakeup'] or fx.decision(task)!=state['cto_decision']
                or any(reads.get(p,{}).get('lines',0)<=0 or reads[p]['lines']!=reads[p].get('total_lines') for p in config['paths'])):
            raise ValueError('actual complete-read CTO technical hold required')
        plans.validate_experiment(experiment['proof'],identity)
        if (experiment['stage']!='complete' or identity['source_task']!=config['predecessor_plan']
                or identity['issue_id']!=config['issue_id']
                or experiment['proof']['original_manifest_sha256']!=config['manifest_sha256']):
            raise ValueError('same preserved original and completed experiment required')
        info=b.docker('GET','/containers/'+experiment['container_id']+'/json');jobs.verify_job(info,identity['payload'])
        if info['State']['Running'] or info['State']['Status']!='exited' or info['State']['ExitCode']!=0:
            raise ValueError('completed predecessor experiment required')
        raw=b.docker_stdout(info['Id'],include_stderr=False,limit=32768)
        if hashlib.sha256(raw.encode()).hexdigest()!=experiment['receipt_sha256'] or json.loads(raw)!=experiment['proof']:
            raise ValueError('predecessor immutable receipt drift')
        variant=experiment['proof']['variant_test_sha256']
        labels=b.docker('GET','/volumes/'+config['volume']).get('Labels',{})
        if (labels.get('delivery-kit.owner')!=b.OWNER or labels.get('delivery-kit.source-task')!=source
                or labels.get('delivery-kit.diagnostic-only')!='true'):
            raise ValueError('owned frozen failed submission required')
        info=b.docker('GET','/containers/'+container_id+'/json');jobs.verify_job(info,job_payload(b,config,variant))
        if info['State']['Running'] or info['State']['Status']!='exited' or info['State']['ExitCode']!=0:
            raise ValueError('completed exact read-only line experiment required')
        raw=b.docker_stdout(info['Id'],include_stderr=False,limit=4096);proof=json.loads(raw)
        if proof.get('variant_test_sha256')!=variant:raise ValueError('executed hypothesis variant drift')
        changed,new=prepare(config,state,proof,qualification)
        new['line_recipe_reconciliation'].update(container_id=container_id,receipt_sha256=hashlib.sha256(raw.encode()).hexdigest())
        try:import calibration_rework as lane
        except ImportError:from broker import calibration_rework as lane
        lane.instruction(changed,new)
        with b.db() as con:
            current=con.execute('SELECT config,state FROM calibration_failure_plans WHERE source_task=?',(source,)).fetchone()
            if tuple(current)!=tuple(row):raise ValueError('hold changed during experiment authentication')
            con.execute('UPDATE calibration_failure_plans SET config=?,state=? WHERE source_task=?',
                (json.dumps(changed,sort_keys=True),json.dumps(new,sort_keys=True),source))
            held=handoffs.load(con,source);data=json.loads(held['data'])
            data.update(required_action='CTO_review_executed_line_recipe_then_independent_Tech_Lead',
                calibration_failure_plan=dict(source_task=source,manifest_sha256=changed['manifest_sha256'],state=new))
            handoffs.save(con,source,changed['issue_id'],'calibration_failure_plan',changed['cto'],data,time.time())
        return new
