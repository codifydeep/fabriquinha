"""Source-bound CTO proposal for exhausted test authors; never an author reset."""
import hashlib
import json
import re
import time
import uuid


def initialize(con):
    con.execute('CREATE TABLE IF NOT EXISTS test_decompositions(source_task TEXT PRIMARY KEY,config TEXT,state TEXT)')
    con.execute('CREATE TABLE IF NOT EXISTS decomposition_stream_failures(source_task TEXT,task_id TEXT,receipt TEXT,PRIMARY KEY(source_task,task_id))')


def capture_stream_failure(b,payload):
    """Observe controller-bound native failure and scoped proxy metadata before replacement."""
    try:import native
    except ImportError:from broker import native
    if not isinstance(payload,dict) or set(payload)!={'source_task','previous_task'}:raise ValueError('exact stream source required')
    for v in payload.values():
        if str(uuid.UUID(v))!=v:raise ValueError('canonical stream source required')
    with b.LOCK:
        with b.db() as con:
            initialize(con)
            old=con.execute('SELECT receipt FROM decomposition_stream_failures WHERE source_task=? AND task_id=?',
                (payload['source_task'],payload['previous_task'])).fetchone()
            if old:return json.loads(old[0])
            row=con.execute('SELECT config,state FROM test_decompositions WHERE source_task=?',(payload['source_task'],)).fetchone()
            if not row:raise ValueError('registered stream diagnosis required')
            cfg,state=json.loads(row[0]),json.loads(row[1])
            bindings=con.execute('SELECT n.request_id,g.mode,l.status FROM native_bindings n JOIN grants g USING(request_id) '
                'JOIN leases l USING(request_id) WHERE n.task_id=?',(payload['previous_task'],)).fetchall()
            if (state.get('stage')!='blocked' or state.get('task_id')!=payload['previous_task']
                    or not state.get('allocation_repair') or len(bindings)!=1
                    or bindings[0][1]!='planning' or bindings[0][2] not in ('failed','closed')):
                raise ValueError('exact failed planning recipient required')
        settings=json.loads((b.STATE/'native.json').read_text())
        task=native.task_record(settings,payload['previous_task'],cfg['cto'])
        if task.get('status')!='failed' or task.get('wakeup_id')!=state.get('wakeup_id'):
            raise ValueError('failed stream wakeup required')
        if any(m.get('type') in ('tool_use','tool_result') for m in native.task_messages(settings,task['id'])):
            raise ValueError('zero tool side effects required')
        proxy=b.docker('GET','/containers/'+b.PREFIX+'-model-proxy-1/json')
        expected=state['allocation_repair']['request']['probe']['proxy_image']
        if not proxy or proxy.get('Image')!=expected or proxy.get('Config',{}).get('Labels',{}).get('com.docker.compose.project')!=b.PREFIX:
            raise ValueError('failed scoped proxy identity required')
        records=[]
        for line in b.docker_stdout(b.PREFIX+'-model-proxy-1',limit=262144).splitlines():
            try:event=json.loads(line)
            except ValueError:continue
            if event.get('event')=='model_proxy_request' and event.get('execution_id')==bindings[0][0]:records.append(event)
        if (len(records)!=1 or records[0].get('status')!=502
                or records[0].get('artifact_rejection_category')!='upstream_stream_error'
                or type(records[0].get('call_number')) is not int):
            raise ValueError('one observed upstream stream failure required')
        receipt={**payload,'execution_id':bindings[0][0],'proxy_image':expected,
            'category':'upstream_stream_error','call_number':records[0]['call_number'],'tool_calls':0,
            'provenance':'controller-bound-native-failure-and-scoped-proxy-log',
            'event_sha256':hashlib.sha256(json.dumps(records[0],sort_keys=True).encode()).hexdigest()}
        with b.db() as con:con.execute('INSERT INTO decomposition_stream_failures VALUES (?,?,?)',
            (payload['source_task'],payload['previous_task'],json.dumps(receipt,sort_keys=True)))
        return receipt


def validate_stream_probe(proof,proxy_image):
    if (not isinstance(proof,dict) or proof.get('schema')!='read-stream-recovery-probe-v1'
            or proof.get('status')!='passed' or proof.get('proxy_image')!=proxy_image
            or proof.get('transport')!='real-http-synthetic-upstream'
            or proof.get('real_model_calls')!=0 or proof.get('durable_calls')!=4
            or proof.get('delivery_approval') is not False or proof.get('product_retry') is not False
            or any(proof.get(k) is not True for k in ('single_retry_verified','valid_response_only',
                'repeated_failure_blocked','restart_blocked','write_retry_forbidden','payload_absent','fixture_removed'))):
        raise ValueError('installed isolated HTTP stream recovery proof required')


def validate_probe(proof,worker_image,*,eof=False,allocation=False,deterministic=False):
    from model_policy import MODEL
    if (not isinstance(proof,dict) or proof.get('schema')!=('acp-decomposition-probe-v4' if deterministic else 'acp-decomposition-probe-v3' if allocation else 'acp-decomposition-probe-v2' if eof else 'acp-decomposition-probe-v1')
            or proof.get('status')!='passed' or proof.get('model')!=MODEL
            or proof.get('worker_image')!=worker_image
            or any(proof.get(k) is not True for k in ('prompt_completed','full_reads_verified',
                'proposal_valid','fixture_unchanged','fixture_removed'))
            or proof.get('delivery_approval') is not False or proof.get('product_retry') is not False
            or proof.get('unit_count')!=2
            or not re.fullmatch(r'sha256:[a-f0-9]{64}',str(proof.get('proxy_image','')))
            or not re.fullmatch(r'[a-f0-9]{64}',str(proof.get('proposal_sha256','')))
            or str(uuid.UUID(proof['execution_id']))!=proof['execution_id']):
        raise ValueError('bound actual read-only decomposition transport proof required')
    inspection=proof.get('inspection') or {}
    if (inspection.get('uid')!=10000 or inspection.get('bytes')!=(22 if eof else 23)
            or inspection.get('sha256')!=('f8b2eb37b0ef6aa2351a68a11036de171473f0814e5c78ed464f824f2b47a217' if eof else '5e41ba724966db023c31ce32089f0ef752e3a33131c12af74856ce99b32b0504')
            or any(inspection.get(k) is not True for k in ('syntax_valid','baseline_unchanged','credentials_absent'))):
        raise ValueError('immutable fixture and credential isolation proof required')
    if eof and (proof.get('unterminated_fixture') is not True or proof.get('read_contract')!='logical-lines-eof-v1'):
        raise ValueError('actual unterminated EOF fixture required')
    if allocation and (not eof or proof.get('proposal_contract')!='criterion-allocation-v2'
            or proof.get('criteria_count')!=22 or proof.get('allocated_criteria_count')!=22):
        raise ValueError('actual complete 22-criterion allocation proof required')
    if deterministic and (not allocation or proof.get('deterministic_reads') is not True
            or proof.get('controller_read_requests')!=3 or proof.get('decision_model_calls')!=1
            or proof.get('dispatch_provenance')!='controller_request_not_read_evidence'):
        raise ValueError('actual native read execution and deterministic dispatch proof required')


def eof_failure_evidence(messages,required_files):
    """Diagnose rejected native output, never promote it into valid read evidence."""
    paths={'/evidence/candidate/'+p for p in required_files}
    calls={m.get('call_id') for m in messages if m.get('type')=='tool_use' and m.get('tool')=='read_file'}
    found=[]
    for m in messages:
        raw=m.get('output')
        if (m.get('type')!='tool_result' or m.get('call_id') not in calls
                or m.get('output_truncated') or not isinstance(raw,str)):
            continue
        match=re.fullmatch(r'Read (/evidence/candidate/[A-Za-z0-9_./-]+)(?: \(from line 1(?:, limit [1-9][0-9]*)?\))? — 0 total lines\n\n(`{3,})[^\n]*\n1\|([^\n]+)\n\2',raw)
        if match and match[1] in paths and not match[3].endswith('... [truncated]'):
            found.append({'path':match[1],'output_sha256':hashlib.sha256(raw.encode()).hexdigest(),
                          'reported_lines':0,'numbered_lines':1})
    if not found:raise ValueError('observed rejected zero-line EOF result required')
    return found


def parse_proposal(task,messages):
    # Do not widen the general technical-decision parser or its authority.
    text=(task.get('result') or {}).get('output')
    if not isinstance(text,str) or not text.strip():
        text=''.join(m.get('content') or '' for m in messages if m.get('type')=='text')
    if not 1<=len(text)<=6000:raise ValueError('bounded decomposition JSON required')
    decision=json.loads(text)
    if not isinstance(decision,dict):raise ValueError('decomposition object required')
    return decision


def validate_result(config, task, decision, reads):
    if config.get('proposal_contract')=='criterion-allocation-v2':
        return validate_allocation(config,task,decision,reads)
    if (task.get('agent_id') != config['cto'] or task.get('status') != 'completed'
            or not isinstance(decision,dict)
            or set(decision) != {'action','reason','optional_files','units'}
            or decision['action'] != 'propose_test_decomposition' or decision['optional_files'] != []
            or not isinstance(decision['reason'],str) or not 1 <= len(decision['reason']) <= 1200
            or not isinstance(decision['units'],list) or not 2 <= len(decision['units']) <= 4):
        raise ValueError('independent bounded CTO decomposition required')
    paths=['/evidence/candidate/'+f for f in config['required_files']]
    if any(p not in reads or type(reads[p].get('lines')) is not int or reads[p]['lines'] <= 0
           or reads[p]['lines'] != reads[p].get('total_lines') for p in paths):
        raise ValueError('complete immutable evidence reads required')
    seen=set(); covered=[]
    for index,unit in enumerate(decision['units'],1):
        if (not isinstance(unit,dict) or set(unit) != {'id','depends_on','criteria','objective'}
                or unit['id'] != 'U'+str(index) or unit['id'] in seen
                or not isinstance(unit['depends_on'],list) or len(set(unit['depends_on'])) != len(unit['depends_on'])
                or set(unit['depends_on']) != (set() if index==1 else {'U'+str(index-1)})
                or not isinstance(unit['criteria'],list) or not unit['criteria']
                or any(c not in config['criteria'] for c in unit['criteria'])
                or not isinstance(unit['objective'],str) or not 1 <= len(unit['objective']) <= 300):
            raise ValueError('ordered incremental units with unchanged scope required')
        covered.extend(unit['criteria']);seen.add(unit['id'])
    if set(covered) != set(config['criteria']) or len(covered) != len(set(covered)):
        raise ValueError('every original criterion must be covered exactly once')
    if config.get('kind') in ('admission_controls_v1','verified_controls_v1') and (len(decision['units'])!=2
            or any(len(u['criteria'])!=1 for u in decision['units'])):
        raise ValueError('exactly two isolated negative controls required')
    return {'source_task':config['source_task'],'decision_task':task['id'],
        'diagnostic_sha256':config['diagnostic_sha256'],
        'execution_authorized':False,'delivery_approval':False,'baseline_edits_allowed':False,
        'read_evidence':{p:reads[p] for p in paths},
        'proposal_sha256':hashlib.sha256(json.dumps(decision,sort_keys=True).encode()).hexdigest()}


def validate_allocation(config,task,decision,reads):
    if (not isinstance(decision,dict) or set(decision)!={'action','reason','optional_files','units','assignments'}
            or not isinstance(decision['assignments'],dict)
            or set(decision['assignments'])!=set(config['criteria'])
            or not isinstance(decision['units'],list) or not 2<=len(decision['units'])<=4):
        raise ValueError('complete explicit criterion allocation required')
    ids=[]
    for unit in decision['units']:
        if not isinstance(unit,dict) or set(unit)!={'id','depends_on','objective'} or not isinstance(unit['id'],str):
            raise ValueError('allocation unit contract required')
        ids.append(unit['id'])
    if any(not isinstance(v,str) or v not in ids for v in decision['assignments'].values()):
        raise ValueError('criterion assignment to existing unit required')
    normalized={k:v for k,v in decision.items() if k!='assignments'}
    normalized['units']=[{**u,'criteria':[c for c in config['criteria'] if decision['assignments'][c]==u['id']]}
                         for u in decision['units']]
    certificate=validate_result({k:v for k,v in config.items() if k!='proposal_contract'},task,normalized,reads)
    certificate.update(proposal_contract='criterion-allocation-v2',normalized_units=normalized['units'],
        allocated_criteria_count=len(decision['assignments']),
        proposal_sha256=hashlib.sha256(json.dumps(decision,sort_keys=True).encode()).hexdigest())
    return certificate


def validate_escalation(config, task, decision, reads):
    """An authentic refusal is a technical impediment, not a malformed proposal."""
    if (config.get('kind')!='admission_controls_v1' or task.get('agent_id')!=config['cto']
            or task.get('status')!='completed' or config['cto']==config['author']
            or not isinstance(decision,dict) or set(decision)!={'action','reason','optional_files','units'}
            or decision['action']!='escalate_cto' or decision['optional_files']!=[] or decision['units']!=[]
            or not isinstance(decision['reason'],str) or not 1<=len(decision['reason'])<=1200):
        raise ValueError('independent bounded CTO impediment required')
    paths=['/evidence/candidate/'+p for p in config['required_files']]
    if any(type(reads.get(p,{}).get('lines')) is not int or reads[p]['lines']<=0
            or reads[p]['lines']!=reads[p].get('total_lines') for p in paths):
        raise ValueError('complete immutable evidence reads required')
    return dict(source_task=config['source_task'],decision_task=task['id'],
        diagnostic_sha256=config['diagnostic_sha256'],delivery_approval=False,execution_authorized=False,
        findings_verified=False,owner=config['cto'],
        read_evidence={p:reads[p] for p in paths},
        decision_sha256=hashlib.sha256(json.dumps(decision,sort_keys=True).encode()).hexdigest())


def advance(config,state,runs,effects,*,now=None):
    if (state.get('stage')=='blocked' and state.get('category')=='decomposition_context_too_large'
            and not state.get('wakeup_id') and not state.get('task_id')):
        state={**state,'stage':'pending','pre_dispatch_failure':{
            'category':'decomposition_context_too_large','no_execution_dispatched':True}}
    if state['stage'] != 'pending':return state
    now=time.time() if now is None else now
    allocation=state.get('proposal_contract')=='criterion-allocation-v2'
    if allocation:config={**config,'proposal_contract':'criterion-allocation-v2'}
    if not state.get('wakeup_id'):
        note=('CTO: no executable test methods. Read ALL immutable evidence. '
            'Do not infer truncation or broken permissions from size alone. Propose 2-4 '
            'SEQUENTIAL units U1..U4, incrementally building the SAME new test using existing '
            'faithful DOM/Node harness patterns. U1: compact real failing assertion before '
            'helper expansion. Cover each criterion ID exactly once. No writes, shell, tests, '
            'scope relaxation, delivery approval or author restart. Proposal ONLY; execution '
            'requires a separate checkpoint contract. Return JSON action=propose_test_decomposition '
            '(or escalate_cto),reason<=1200,optional_files=[],units[{id,depends_on,'+('objective}],assignments{EVERY criterion ID:unit ID}. ' if allocation else 'criteria,objective}]. ')+
            'Each unit after U1 depends ONLY on its immediate predecessor.\n'
            'Criteria: '+json.dumps(config['criteria'],ensure_ascii=False)+'\n'
            'Measured diagnostic: '+json.dumps({k:config['diagnostic'].get(k) for k in ('category','files')},sort_keys=True)+'\n'
            +('DELIVERY_TEST_DECOMPOSITION_V2\n' if allocation else 'DELIVERY_TEST_DECOMPOSITION_V1\n')+'DELIVERY_STRUCTURED_DECISION_V1:technical\n'
            +''.join('DELIVERY_DECOMPOSITION_CRITERION:'+c+'\n' for c in config['criteria'])
            +''.join('DELIVERY_REVIEW_READ_PATH:/evidence/candidate/'+f+'\n' for f in config['required_files']))
        if state.get('deterministic_reads'):
            note+='\nController requests required reads; only actual tool results qualify.\nDELIVERY_DETERMINISTIC_READ_V1\n'
        elif state.get('stream_repair'):
            note+='\nRead-stream recovery qualified. Prior failure remains; read all files anew.\n'
        elif state.get('reader_repair'):
            note+='\nEOF reader qualified. Prior rejected reads are NOT evidence; read all files anew.\n'
        elif state.get('transport_repair'):
            note+='\nQUALIFIED TRANSPORT REPAIR: exact read schemas and proposal parser were repaired. '
            note+='Previous rejection remains preserved; inspect actual files anew.\n'
        if config.get('kind')=='verified_controls_v1':
            note=('CTO: APPROVED HARNESS, NEW NEGATIVE CONTROLS ONLY. Read all immutable files. '
                'Actual original four tests pass; mutation retain_query survives, mutation '
                'allow_stale_status survives; allow_stale_query fails the existing assertion. '
                'The current stale-status assertion checks rendered_after_current_status, '
                'not the recorded rendered_after_stale_status. The driver never clears '
                'the search field. Propose exactly two sequential additive tests-only units '
                'U1 then U2, one criterion per unit, against this approved harness. '
                'Preserve all existing tests/assertions and the passing driver. If a new '
                'observation is needed, use an additional isolated driver, not a rewrite. '
                'No product edits, writes, shell, execution claims or author authorization. '
                'Return JSON action=propose_test_decomposition,reason<=1200,optional_files=[], '
                'units[{id,depends_on,criteria,objective}]. U1 depends_on=[]; U2 depends_on=[U1]; '
                'each objective<=300 characters.\nCriteria: '+json.dumps(config['criteria'])+'\n'
                'DELIVERY_TEST_DECOMPOSITION_V1\nDELIVERY_STRUCTURED_DECISION_V1:technical\n'
                'DELIVERY_TYPED_DECOMPOSITION_V1\nDELIVERY_DETERMINISTIC_READ_V1\n'
                +''.join('DELIVERY_DECOMPOSITION_CRITERION:'+c+'\n' for c in config['criteria'])
                +''.join('DELIVERY_REVIEW_READ_PATH:/evidence/candidate/'+f+'\n' for f in config['required_files']))
        if config.get('kind')=='admission_controls_v1':
            note=('CTO SPIKE: inspect the frozen rejected delivery, not a mutable workspace. '
                'Two authors exhausted scoped controls work; missing methods remain. '
                'Do not repeat whole-harness repair, invent executed experiments, approve '
                'the delivery, change product code, or grant a retry. Propose EXACTLY TWO '
                'small sequential tests-only experiments U1 then U2. Each covers exactly '
                'one criterion. U2 builds on the independently reviewed U1 artifact. '
                'Each objective specifies the intervention and observable assertion. '
                'Preserve existing tests. Assess whether the current driver supports the '
                'control; if not, escalate_cto rather than treating a plan as a fix. '
                'No executable methods, shell, writes or tests in this planning execution. '
                'Execution requires a separate evidence-bound checkpoint contract. '
                'Return JSON action=propose_test_decomposition (or escalate_cto), '
                'reason<=1200,optional_files=[],units[{id,depends_on,criteria,objective}]. '
                'U1 depends_on=[]; U2 depends_on=[U1]. Objectives <=300 characters.\n'
                'Criteria: '+json.dumps(config['criteria'],ensure_ascii=False)+'\n'
                'DELIVERY_TEST_DECOMPOSITION_V1\nDELIVERY_STRUCTURED_DECISION_V1:technical\n'
                'DELIVERY_TYPED_DECOMPOSITION_V1\n'
                'DELIVERY_DETERMINISTIC_READ_V1\n'
                +''.join('DELIVERY_DECOMPOSITION_CRITERION:'+c+'\n' for c in config['criteria'])
                +''.join('DELIVERY_REVIEW_READ_PATH:/evidence/candidate/'+f+'\n' for f in config['required_files']))
        marker=hashlib.sha256((config['source_task']+':test-decomposition:'+config['diagnostic_sha256']
            +(':qualified-read-proposal-repair-v1' if state.get('transport_repair') else '')
            +(':qualified-eof-reader-repair-v1' if state.get('reader_repair') else '')
            +(':qualified-criterion-allocation-v2' if allocation else '')
            +(':qualified-read-stream-recovery-v1' if state.get('stream_repair') else '')
            +(':controller-read-dispatch-v1' if state.get('deterministic_reads') else '')).encode()).hexdigest()
        if state.get('bounded_adapter_recovery'):
            marker=hashlib.sha256((marker+':typed-decomposition-adapter-v1').encode()).hexdigest()
        if len(note)>3900:return {**state,'stage':'blocked','category':'decomposition_context_too_large'}
        start=effects.ensure_planning_start if config.get('kind')=='verified_controls_v1' else effects.ensure_wakeup
        wake=start(config['issue_id'],config['cto'],config['source_task'],marker,note,
                                  allow_create=effects.remaining_calls() >= 8)
        return {**state,'wakeup_id':wake['id'],'at':now} if wake else state
    tasks=[r for r in runs if r.get('agent_id')==config['cto'] and r.get('wakeup_id')==state['wakeup_id']]
    if len(tasks)>1:return {**state,'stage':'blocked','category':'duplicate_cto_recipient'}
    if not tasks or tasks[0]['status'] in ('queued','running'):
        return {**state,'stage':'blocked','category':'cto_deadline'} if now-state['at']>1800 else state
    try:
        decision=effects.decomposition_proposal(tasks[0]);reads=effects.read_evidence(tasks[0])
        if config.get('kind')=='admission_controls_v1' and decision.get('action')=='escalate_cto':
            certificate=validate_escalation(config,tasks[0],decision,reads)
            return {**state,'stage':'blocked','category':'cto_scope_escalation','decision':decision,
                'certificate':certificate,'task_id':tasks[0]['id'],
                'next_action':'qualify_harness_prerequisites_before_control_author_dispatch'}
        certificate=validate_result(config,tasks[0],decision,reads)
        return {**state,'stage':'proposal_ready','decision':decision,'certificate':certificate,
                'task_id':tasks[0]['id']}
    except (ValueError,KeyError,TypeError):
        return {**state,'stage':'blocked','category':'invalid_or_unread_decomposition','task_id':tasks[0]['id']}


def register(b,payload):
    try:import native,handoffs,artifact_transport_recovery
    except ImportError:from broker import native,handoffs,artifact_transport_recovery
    if not isinstance(payload,dict) or set(payload)!={'source_task'} or str(uuid.UUID(payload['source_task']))!=payload['source_task']:
        raise ValueError('exact decomposition source identity required')
    source=payload['source_task']
    with b.LOCK:
        with b.db() as con:
            initialize(con)
            prior=con.execute('SELECT state FROM test_decompositions WHERE source_task=?',(source,)).fetchone()
            if prior:return json.loads(prior[0])
            row=con.execute('SELECT * FROM delivery_handoffs WHERE source_task=?',(source,)).fetchone()
            if not row or row['stage']!='test_first_blocked':raise ValueError('blocked test author required')
            issue=row['issue_id'];data=json.loads(row['data'])
            route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(issue,)).fetchone()[0])
            diagnostic=data.get('diagnostic') or {}
            if (not route.get('enabled') or not route.get('test_first') or route['cto']==route['author']
                    or data.get('error')!='test_first_correction_failed_after_cto_diagnosis'
                    or diagnostic.get('category')!='new_test_no_methods' or diagnostic.get('task_id')!=source
                    or set(diagnostic.get('files',{}))!=set(route['test_first_files'])
                    or con.execute('SELECT 1 FROM test_first_red WHERE issue_id=?',(issue,)).fetchone()
                    or con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running')").fetchone()
                    or con.execute('SELECT 1 FROM test_decompositions WHERE json_extract(config,?)=?',('$.issue_id',issue)).fetchone()):
                raise ValueError('independent idle exhausted tests-only route required')
        settings=json.loads((b.STATE/'native.json').read_text());runs=native.issue_task_runs(settings,issue)
        authors=[r for r in runs if r.get('agent_id')==route['author']]
        if (not authors or max(authors,key=lambda r:(r.get('created_at') or '',r['id']))['id']!=source
                or next(r for r in authors if r['id']==source)['status']!='completed'
                or any(r['status'] in ('queued','running') for r in runs)):
            raise ValueError('latest completed author and idle native tasks required')
        snapshot=artifact_transport_recovery.verify_preserved_failure(b,source,diagnostic,failed=False)
        description=native.issue_record(settings,issue)['description']
        if not isinstance(description,str) or not 1<=len(description)<=4000:raise ValueError('bounded original requirements required')
        parts=re.split(r'(?<=[.!?])\s+',description.strip())
        if not 1<=len(parts)<=32:raise ValueError('bounded criteria count required')
        criteria={'C'+str(i).zfill(2):p for i,p in enumerate(parts,1)}
        markers=b.test_artifact_phase_context(issue,route['author'])
        files=sorted(set(re.findall(r'^DELIVERY_TEST_SOURCE_V1:/workspace/(.+)$',markers,re.M))|set(route['test_first_files']))
        config={'source_task':source,'issue_id':issue,'cto':route['cto'],'author':route['author'],
            'criteria':criteria,'requirements_sha256':hashlib.sha256(description.encode()).hexdigest(),
            'required_files':files,'snapshot':snapshot,'diagnostic':diagnostic,
            'diagnostic_sha256':hashlib.sha256(json.dumps(diagnostic,sort_keys=True).encode()).hexdigest()}
        with b.db() as con:
            current=con.execute('SELECT data,stage FROM delivery_handoffs WHERE source_task=?',(source,)).fetchone()
            if current['data']!=row['data'] or current['stage']!=row['stage']:raise ValueError('decomposition source changed')
            con.execute('INSERT INTO test_decompositions VALUES (?,?,?)',(source,json.dumps(config,sort_keys=True),json.dumps({'stage':'pending'})))
        return {'stage':'pending','source_task':source,'execution_authorized':False}


def repair_transport(b,payload):
    """One qualified changed-transport diagnosis, not a new author attempt."""
    try:import native,artifact_transport_recovery,handoffs
    except ImportError:from broker import native,artifact_transport_recovery,handoffs
    if not isinstance(payload,dict) or set(payload)!={'source_task','previous_task','probe','previous_proxy_image'}:
        raise ValueError('exact diagnostic transport repair identity required')
    for key in ('source_task','previous_task'):
        if str(uuid.UUID(payload[key]))!=payload[key]:raise ValueError('canonical diagnostic identities required')
    deterministic=payload['probe'].get('schema')=='acp-decomposition-probe-v4'
    allocation=deterministic or payload['probe'].get('schema')=='acp-decomposition-probe-v3'
    stream=allocation and 'read_stream_recovery' in payload['probe']
    eof=allocation or payload['probe'].get('schema')=='acp-decomposition-probe-v2'
    validate_probe(payload['probe'],b.IMAGE,eof=eof,allocation=allocation,deterministic=deterministic)
    if stream:validate_stream_probe(payload['probe']['read_stream_recovery'],payload['probe']['proxy_image'])
    repair_key='stream_repair' if stream else 'allocation_repair' if allocation else 'reader_repair' if eof else 'transport_repair'
    if not re.fullmatch(r'sha256:[a-f0-9]{64}',str(payload['previous_proxy_image'])):
        raise ValueError('historical scoped proxy identity required')
    if (allocation or not eof) and payload['previous_proxy_image']==payload['probe']['proxy_image']:
        raise ValueError('changed qualified diagnostic proxy required')
    with b.LOCK:
        with b.db() as con:
            initialize(con)
            row=con.execute('SELECT config,state FROM test_decompositions WHERE source_task=?',(payload['source_task'],)).fetchone()
            if not row:raise ValueError('registered rejected decomposition required')
            config,state=json.loads(row[0]),json.loads(row[1])
            if state.get(repair_key):
                if state[repair_key]['request']!=payload:raise ValueError('diagnostic repair identity drift')
                return state[repair_key]
            if stream:
                prior=(state.get('allocation_repair') or {}).get('request',{}).get('probe',{})
                failure=con.execute('SELECT receipt FROM decomposition_stream_failures WHERE source_task=? AND task_id=?',
                    (config['source_task'],payload['previous_task'])).fetchone()
                if (not failure or prior.get('worker_image')!=b.IMAGE or prior.get('proxy_image')!=payload['previous_proxy_image']):
                    raise ValueError('preserved observed failed stream and allocation contract required')
                stream_evidence=json.loads(failure[0])
                if stream_evidence['proxy_image']!=payload['previous_proxy_image']:raise ValueError('stream proxy identity drift')
            elif allocation:
                prior=(state.get('reader_repair') or {}).get('request',{}).get('probe',{})
                if (prior.get('worker_image')!=b.IMAGE or prior.get('proxy_image')!=payload['previous_proxy_image']):
                    raise ValueError('preserved qualified EOF worker and previous proxy required')
            elif eof:
                prior=(state.get('transport_repair') or {}).get('request',{}).get('probe',{})
                if (not prior or prior.get('worker_image')==b.IMAGE
                        or prior.get('proxy_image')!=payload['previous_proxy_image']
                        or payload['previous_proxy_image']!=payload['probe']['proxy_image']):
                    raise ValueError('changed worker with preserved qualified proxy required')
            current=handoffs.load(con,config['source_task']);data=json.loads(current['data'])
            route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(config['issue_id'],)).fetchone()[0])
            if (state.get('stage')!='blocked' or state.get('category')!='invalid_or_unread_decomposition'
                    or state.get('task_id')!=payload['previous_task'] or current['stage']!='test_first_blocked'
                    or data.get('diagnostic')!=config['diagnostic'] or route.get('cto')!=config['cto']
                    or route.get('author')!=config['author'] or not route.get('enabled')
                    or con.execute('SELECT 1 FROM test_first_red WHERE issue_id=?',(config['issue_id'],)).fetchone()
                    or con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running')").fetchone()):
                raise ValueError('unchanged idle rejected diagnosis without Red required')
        settings=json.loads((b.STATE/'native.json').read_text());runs=native.issue_task_runs(settings,config['issue_id'])
        authors=[r for r in runs if r.get('agent_id')==config['author']]
        cto=[r for r in runs if r.get('agent_id')==config['cto']]
        previous=next((r for r in cto if r['id']==payload['previous_task']),{})
        if (not authors or not cto or max(authors,key=lambda r:(r.get('created_at') or '',r['id']))['id']!=config['source_task']
                or max(cto,key=lambda r:(r.get('created_at') or '',r['id']))['id']!=payload['previous_task']
                or previous.get('status')!=('failed' if stream else 'completed') or previous.get('wakeup_id')!=state.get('wakeup_id')
                or any(r['status'] in ('queued','running') for r in runs)):
            raise ValueError('exact rejected CTO recipient and idle latest source required')
        description=native.issue_record(settings,config['issue_id'])['description']
        if hashlib.sha256(description.encode()).hexdigest()!=config['requirements_sha256']:
            raise ValueError('requirements changed during diagnosis')
        eof_evidence=eof_failure_evidence(native.task_messages(settings,payload['previous_task']),config['required_files']) if eof and not allocation else None
        allocation_evidence=None
        if allocation and not stream:
            try:import handoff_runtime
            except ImportError:from broker import handoff_runtime
            effects=handoff_runtime.Effects(b,settings)
            decision=effects.decomposition_proposal(previous);reads=effects.read_evidence(previous)
            try:validate_result(config,previous,decision,reads)
            except ValueError as error:
                if str(error)!='every original criterion must be covered exactly once':
                    raise ValueError('exact complete-read scope-coverage rejection required') from error
            else:raise ValueError('prior scope rejection required')
            covered=[c for u in decision['units'] for c in u['criteria']]
            allocation_evidence={'proposal_sha256':hashlib.sha256(json.dumps(decision,sort_keys=True).encode()).hexdigest(),
                'missing_criteria':[c for c in config['criteria'] if c not in covered],
                'duplicate_criteria':sorted({c for c in covered if covered.count(c)>1}),
                'complete_read_count':len(config['required_files'])}
        proxy=b.docker('GET','/containers/'+b.PREFIX+'-model-proxy-1/json')
        if (not proxy or proxy.get('Image')!=payload['probe']['proxy_image']
                or not proxy.get('State',{}).get('Running')
                or proxy.get('Config',{}).get('Labels',{}).get('com.docker.compose.project')!=b.PREFIX):
            raise ValueError('qualified installed scoped diagnostic proxy required')
        snapshot=artifact_transport_recovery.verify_preserved_failure(b,config['source_task'],config['diagnostic'],failed=False)
        if snapshot!=config['snapshot']:raise ValueError('diagnostic snapshot identity drift')
        receipt={'request':payload,'previous_rejection':state,'at':time.time(),
            'previous_proxy_provenance':'operator_verified_historical_proxy_identity',
            'execution_authorized':False,'same_class_attempt_limit':1}
        if stream:receipt.update(repair_class='read_stream_recovery_v1',observed_stream_failure=stream_evidence)
        elif allocation:receipt.update(repair_class='criterion_allocation_v2',rejected_scope_evidence=allocation_evidence)
        elif eof:receipt.update(repair_class='logical_lines_eof_v1',rejected_read_evidence=eof_evidence)
        with b.db() as con:
            new={'stage':'pending',repair_key:receipt}
            if eof:new['transport_repair']=state['transport_repair']
            if allocation:new.update(reader_repair=state['reader_repair'],proposal_contract='criterion-allocation-v2')
            if stream:new['allocation_repair']=state['allocation_repair']
            if deterministic:new['deterministic_reads']=True
            con.execute('UPDATE test_decompositions SET state=? WHERE source_task=?',(json.dumps(new,sort_keys=True),config['source_task']))
        return receipt


def mounts(b,binding):
    try:import native
    except ImportError:from broker import native
    with b.db() as con:
        initialize(con);rows=con.execute('SELECT config,state FROM test_decompositions').fetchall()
    for row in rows:
        c,s=json.loads(row[0]),json.loads(row[1])
        if c['issue_id']!=binding['issue_id'] or c['cto']!=binding['agent_id'] or s['stage']!='pending' or not s.get('wakeup_id'):continue
        with b.db() as con:
            bound=con.execute('SELECT task_id FROM native_bindings WHERE request_id=?',(binding['request_id'],)).fetchone()
        if not bound:raise ValueError('decomposition native binding required')
        task=native.task_record(json.loads((b.STATE/'native.json').read_text()),bound[0],binding['agent_id'])
        if task.get('wakeup_id')!=s['wakeup_id']:continue
        v=b.docker('GET','/volumes/'+c['snapshot']['volume']);labels=(v or {}).get('Labels',{})
        if labels.get('delivery-kit.owner')!=b.OWNER or labels.get('delivery-kit.source-task')!=c['source_task']:
            raise ValueError('decomposition snapshot identity mismatch')
        return [{'Type':'volume','Source':c['snapshot']['volume'],'Target':'/evidence/candidate','ReadOnly':True}]
    return []


def tick(b):
    try:import native,handoffs,handoff_runtime
    except ImportError:from broker import native,handoffs,handoff_runtime
    settings=json.loads((b.STATE/'native.json').read_text());effects=handoff_runtime.Effects(b,settings)
    with b.db() as con:initialize(con);rows=con.execute('SELECT config,state FROM test_decompositions').fetchall()
    for row in rows:
        config,state=json.loads(row[0]),json.loads(row[1])
        if state['stage']!='pending' and not (state.get('category')=='decomposition_context_too_large'
                and not state.get('wakeup_id') and not state.get('task_id')):continue
        with b.LOCK:
            if config.get('kind')=='verified_controls_v1':
                try:import u3_controls_intake as controls
                except ImportError:from broker import u3_controls_intake as controls
                with b.db() as con:
                    try:controls.verify(con,config)
                    except (ValueError,KeyError,TypeError):
                        con.execute('UPDATE test_decompositions SET state=? WHERE source_task=?',
                            (json.dumps({**state,'stage':'blocked','category':'approved_controls_source_drift',
                                'owner':config['cto'],'next_action':'Diagnose source drift; no automatic replay'},sort_keys=True),config['source_task']))
                        continue
                try:changed=advance(config,state,native.issue_task_runs(settings,config['issue_id']),effects)
                except Exception as error:
                    changed={**state,'stage':'blocked','category':'controls_dispatch_unavailable',
                        'error_type':type(error).__name__,'execution_authorized':False}
                changed['owner']=config['cto']
                changed['next_action']=('Qualify a new additive tests-only author capability; no product authorization'
                    if changed['stage']=='proposal_ready' else
                    'CTO diagnosis required; no identical replay' if changed['stage']=='blocked' else 'Await current CTO proposal')
                with b.db() as con:
                    controls.verify(con,config)
                    con.execute('UPDATE test_decompositions SET state=? WHERE source_task=?',
                        (json.dumps(changed,sort_keys=True),config['source_task']))
                continue
            if config.get('kind')=='admission_controls_v1':
                try:import admission_controls_spike
                except ImportError:from broker import admission_controls_spike
                with b.db() as con:
                    try:admission_controls_spike.verify_current(con,config)
                    except ValueError:
                        con.execute('UPDATE test_decompositions SET state=? WHERE source_task=?',
                            (json.dumps({**state,'stage':'blocked','category':'admission_source_drift'},sort_keys=True),config['source_task']))
                        continue
                changed=advance(config,state,native.issue_task_runs(settings,config['issue_id']),effects)
                with b.db() as con:
                    admission_controls_spike.verify_current(con,config)
                    con.execute('UPDATE test_decompositions SET state=? WHERE source_task=?',
                        (json.dumps(changed,sort_keys=True),config['source_task']))
                continue
            changed=advance(config,state,native.issue_task_runs(settings,config['issue_id']),effects)
            with b.db() as con:
                current=handoffs.load(con,config['source_task']);data=json.loads(current['data'])
                if current['stage']!='test_first_blocked' or data.get('diagnostic')!=config['diagnostic']:
                    changed={**state,'stage':'blocked','category':'decomposition_source_drift'}
                con.execute('UPDATE test_decompositions SET state=? WHERE source_task=?',(json.dumps(changed,sort_keys=True),config['source_task']))
                data['test_decomposition']={**changed,'required_action':'implement_checkpoint_contract_before_author_dispatch'}
                handoffs.save(con,config['source_task'],config['issue_id'],'test_first_blocked',config['cto'],data,time.time())
