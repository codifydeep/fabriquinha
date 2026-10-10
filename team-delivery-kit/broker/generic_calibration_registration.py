"""Fetch native identities and immutable input-job facts before registration.

Controller-only. No operator/worker supplied approval objects are accepted by
register: it consumes a persisted intake, a real input job and exact native runs.
The producer/reviewer workflow must create those intents separately; missing
intents remain a prerequisite hold, never an implied approval.
"""
import hashlib
import json
import re
import time

try:import generic_calibration_gate as gate
except ImportError:from broker import generic_calibration_gate as gate
from generic_harness_calibration import digest,validate_policy


def context_from_inputs(value,route,intake,proof):
    p=intake['policy'];context=intake['context'];sha=digest(p);validate_policy(p,sha)
    previous=value['previous_new_test_delivery']
    expected_fields={'operation','policy_sha256','candidate_manifest_sha256','previous_manifest_sha256',
        'controls_manifest_sha256','candidate_test_sha256','previous_test_sha256','candidate_methods',
        'previous_methods','product_sha256','control_sha256','tests_executed','execution_authorized','delivery_approval'}
    gate.require(isinstance(proof,dict) and set(proof)==expected_fields
        and proof['operation']=='generic_calibration_inputs_v1'
        and all(proof[k] is False for k in ('tests_executed','execution_authorized','delivery_approval')))
    gate.require(intake['previous']==previous and p['source_task']==value['source_task']
        and p['execution_sha256']==digest(value) and p['plan_sha256']==value['plan_sha256']
        and set(p['criteria'])==set(value['criteria'])
        and context['issue_id']==route['issue_id'] and context['author']==route['author']
        and context['cto']==route['cto'] and context['reviewer']==route['techlead']
        and len({context['author'],context['cto'],context['reviewer']})==3
        and set(p['test_sha256'])==set(value['steps'][0]['editable_files'])==set(route['test_first_files'])
        and proof['policy_sha256']==sha and proof['previous_manifest_sha256']==previous['manifest_sha256']
        and proof['previous_test_sha256']==previous['test_sha256']
        and proof['candidate_test_sha256']==p['test_sha256']
        and proof['previous_methods']==p['previous_methods']==context['previous_methods'])
    for key in ('source_task','execution_sha256','plan_sha256','criteria'):
        gate.require(context[key]==p[key])
    for key in ('candidate_manifest_sha256','controls_manifest_sha256'):gate.require(proof[key]==p[key])
    normalized=lambda classes:{key:sorted(methods) for key,methods in classes.items()}
    gate.require(proof['candidate_methods']=={m['path']:normalized(m['classes']) for m in p['modules']})
    gate.require(set(proof['product_sha256'])=={m['product_path'] for m in p['modules']}
        and set(proof['control_sha256'])==set(context['control_files']))
    for mapping in (proof['product_sha256'],proof['control_sha256']):
        gate.require(all(isinstance(v,str) and bool(re.fullmatch('[a-f0-9]{64}',v)) for v in mapping.values()))
    return context


def copy_matches(intake,identity,state):
    p=intake['policy'];context=intake['context']
    gate.require(state.get('stage')=='complete')
    result=state.get('result',{});raw=result.get('output')
    gate.require(type(result.get('exit_code')) is int and result['exit_code']==0
        and result.get('approval') is False and isinstance(raw,str)
        and hashlib.sha256(raw.encode()).hexdigest()==result.get('output_sha256'))
    prepared=json.loads(raw)
    gate.require(prepared.get('manifest_sha256')==p['candidate_manifest_sha256']
        and prepared.get('test_sha256')==p['test_sha256'])
    payload=identity['payload']
    gate.require(payload['Labels'].get('delivery-kit.test-first-task')==context['author_task'])
    target=[m for m in payload['HostConfig']['Mounts'] if m.get('Target')=='/snapshot']
    gate.require(len(target)==1 and target[0].get('Source')==context['candidate_volume'])
    return prepared


def input_payload(b,intake):
    record=dict(policy=intake['policy'],policy_sha256=digest(intake['policy']),context=intake['context'])
    payload=gate.payload(b,record);previous=intake['previous']
    gate.require(previous['volume'].startswith(b.PREFIX+'-')
        and bool(re.fullmatch('[A-Za-z0-9_.-]{1,200}',previous['volume'])))
    gate.require(previous['volume'] not in {m['Source'] for m in payload['HostConfig']['Mounts']})
    payload['Cmd']=['/generic_calibration_input_probe.py','/candidate','/previous','/controls',
        '/policy/policy.json',record['policy_sha256'],previous['manifest_sha256']]
    payload['HostConfig']['Mounts'].append(dict(Type='volume',Source=previous['volume'],Target='/previous',ReadOnly=True))
    payload['Labels']['delivery-kit.calibration-phase']='inputs'
    return payload


def initialize(con):
    gate.initialize(con)
    con.execute('CREATE TABLE IF NOT EXISTS generic_calibration_intakes('
        'issue_id TEXT,author_task TEXT,config TEXT,PRIMARY KEY(issue_id,author_task))')
    con.execute('CREATE TABLE IF NOT EXISTS generic_calibration_input_jobs('
        'job_key TEXT PRIMARY KEY,identity TEXT,state TEXT)')


def run_inputs(b,con,intake,value,route,*,now=None):
    """Controller-only read/AST job; requires an exact durable intake.

    This is not admission or approval. The caller holds the controller lock;
    register still authenticates native approvals after the probe completes.
    Persist effects before sending them and never replay an uncertain POST.
    """
    try:import harness_qualification,test_first_job
    except ImportError:from broker import harness_qualification,test_first_job
    initialize(con);context=intake['context'];key=intake['probe_job_key']
    stored=con.execute('SELECT config FROM generic_calibration_intakes WHERE issue_id=? AND author_task=?',
        (context['issue_id'],context['author_task'])).fetchone()
    gate.require(stored and json.loads(stored[0])==intake)
    expected=input_payload(b,intake)
    expected['Env']=harness_qualification.image_environment(
        gate.SimpleNamespace(IMAGE=expected['Image'],docker=b.docker))
    identity=dict(name=b.PREFIX+'-calibration-inputs-'+digest(intake)[:24],
        payload=expected,intake_sha256=digest(intake))
    row=con.execute('SELECT identity,state FROM generic_calibration_input_jobs WHERE job_key=?',(key,)).fetchone()
    now=time.time() if now is None else now
    if row:
        gate.require(json.loads(row[0])==identity);state=json.loads(row[1])
        gate.require(state['stage']!='blocked')
        if state['stage']=='complete':
            result=state['result'];raw=result['output']
            gate.require(result['approval'] is False and result['exit_code']==0
                and hashlib.sha256(raw.encode()).hexdigest()==result['output_sha256'])
            context_from_inputs(value,route,intake,json.loads(raw))
            return result
    else:
        gate.require(b.docker('GET','/containers/'+identity['name']+'/json') is None)
        state=dict(stage='prepared',deadline=now+600,delivery_approval=False)
        con.execute('INSERT INTO generic_calibration_input_jobs VALUES(?,?,?)',
            (key,json.dumps(identity,sort_keys=True),json.dumps(state,sort_keys=True)));con.commit()
    def save(**changes):
        state.update(changes)
        con.execute('UPDATE generic_calibration_input_jobs SET state=? WHERE job_key=?',
            (json.dumps(state,sort_keys=True),key));con.commit()
    if now>=state['deadline']:
        save(stage='blocked',category='input_observation_deadline')
        raise ValueError('input deadline; retain exact job for diagnosis')
    # Ownership is checked before every effect, not inferred from volume names.
    record=dict(policy=intake['policy'],policy_sha256=digest(intake['policy']),context=context)
    gate.validate_volumes(b,record)
    previous=b.docker('GET','/volumes/'+intake['previous']['volume']) or {}
    tags=previous.get('Labels',{})
    gate.require(tags.get('delivery-kit.owner')==b.OWNER
        and tags.get('delivery-kit.test-first-task')==intake['previous']['task_id'])
    if state['stage']=='prepared':
        save(stage='create_intent')
        try:b.docker('POST','/containers/create?name='+identity['name'],expected)
        except TimeoutError:raise TimeoutError('observe exact input create; never repeat POST') from None
    info=b.docker('GET','/containers/'+identity['name']+'/json')
    if info is None:raise TimeoutError('observe exact input handle; never recreate')
    test_first_job.verify(b,info,expected)
    if state['stage']=='create_intent':save(stage='created',container_id=info['Id'])
    gate.require(info['Id']==state['container_id'])
    if state['stage']=='created':
        gate.require(info['State']['Status']=='created');save(stage='start_intent')
        try:b.docker('POST','/containers/'+info['Id']+'/start')
        except TimeoutError:raise TimeoutError('observe exact input start; never repeat POST') from None
        info=b.docker('GET','/containers/'+info['Id']+'/json')
        if info is None:raise TimeoutError('observe recorded input start')
        test_first_job.verify(b,info,expected)
        gate.require(info['Id']==state['container_id'])
    if info['State']['Status']!='exited':raise TimeoutError('input pending; observe same handle')
    raw=b.docker_stdout(info['Id'],include_stderr=info['State']['ExitCode']!=0,limit=65536)
    sha=hashlib.sha256(raw.encode()).hexdigest()
    try:
        gate.require(info['State']['ExitCode']==0)
        context_from_inputs(value,route,intake,json.loads(raw))
    except (ValueError,KeyError,TypeError):
        save(stage='blocked',category='executed_input_rejected',output_sha256=sha,
            exit_code=info['State']['ExitCode'])
        raise ValueError('actual input rejected; no identical retry') from None
    result=dict(container_id=info['Id'],exit_code=0,approval=False,output=raw,output_sha256=sha)
    save(stage='complete',result=result)
    return result


def register(b,issue,author_task):
    try:import remediation_runtime_guard as guard,remediation_admission,native,technical_remediation_plan as plans,harness_qualification
    except ImportError:from broker import remediation_runtime_guard as guard,remediation_admission,native,technical_remediation_plan as plans,harness_qualification
    with b.LOCK:
        value=guard.qualified(b,issue)
        gate.require(value and value.get('amendment',{}).get('kind')=='inherited_frozen_suite')
        config,approved=remediation_admission.Effects(b).plan(value['source_task'])
        gate.require(approved['plan_sha256']==value['plan_sha256'])
        with b.db() as con:
            initialize(con)
            row=con.execute('SELECT config FROM generic_calibration_intakes WHERE issue_id=? AND author_task=?',
                (issue,author_task)).fetchone()
            if not row:raise ValueError('generic calibration independently reviewed input intent required')
            intake=json.loads(row[0]);context=intake['context']
            gate.require(context['issue_id']==issue and context['author_task']==author_task)
            route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(issue,)).fetchone()[0])
            gate.require(route['cto']==config['cto'] and route['techlead']==config['reviewer']
                and route['author']==config['original_author'])
            copy=con.execute('SELECT identity,state FROM test_first_jobs WHERE job_key=?',(author_task+':copy',)).fetchone()
            gate.require(copy is not None);copy_matches(intake,*map(json.loads,copy))
            job=con.execute('SELECT identity,state FROM generic_calibration_input_jobs WHERE job_key=?',
                (intake['probe_job_key'],)).fetchone()
            gate.require(job is not None);identity,state=map(json.loads,job)
            # Every approval task has one exact closed planning lease. A model's
            # statement that it reviewed a file is not a native binding.
            for tid,actor,mode in ((intake['proposal_task'],route['cto'],'planning'),
                    (intake['review_task'],route['techlead'],'planning'),(author_task,route['author'],'implementation')):
                rows=con.execute('SELECT n.*,l.status FROM native_bindings n JOIN leases l USING(request_id) WHERE n.task_id=?',
                    (tid,)).fetchall()
                gate.require(len(rows)==1 and rows[0]['status']=='closed'
                    and rows[0]['agent_id']==actor and rows[0]['issue_id']==issue
                    and rows[0]['scope'].split(':')[-2:]==[mode,tid])
        expected=input_payload(b,intake)
        expected['Env']=harness_qualification.image_environment(
            gate.SimpleNamespace(IMAGE=expected['Image'],docker=b.docker))
        gate.require(identity.get('payload')==expected and state.get('stage')=='complete')
        result=state.get('result',{});raw=result.get('output')
        gate.require(type(result.get('exit_code')) is int and result['exit_code']==0
            and result.get('approval') is False and isinstance(raw,str)
            and hashlib.sha256(raw.encode()).hexdigest()==result.get('output_sha256'))
        proof=json.loads(raw);context_from_inputs(value,route,intake,proof)
        probe_previous=b.docker('GET','/volumes/'+intake['previous']['volume']) or {}
        tags=probe_previous.get('Labels',{})
        gate.require(tags.get('delivery-kit.owner')==b.OWNER
            and tags.get('delivery-kit.test-first-task')==intake['previous']['task_id'])
        fx=plans.Effects(b)
        gate.require(all(fx.settings['agents'].get(actor)=='planning' for actor in (route['cto'],route['techlead'])))
        gate.require(fx.settings['agents'].get(route['author'])=='implementation')
        authored=fx.task(author_task,route['author'])
        gate.require(authored.get('status')=='completed' and authored.get('issue_id')==issue)
        proposal=fx.task(intake['proposal_task'],route['cto']);review=fx.task(intake['review_task'],route['techlead'])
        record=gate.qualify(intake['policy'],context,proposal,review,fx.reads(proposal),fx.reads(review))
        gate.validate_volumes(b,record)
        with b.db() as con:
            current=con.execute('SELECT config FROM generic_calibration_intakes WHERE issue_id=? AND author_task=?',
                (issue,author_task)).fetchone()
            gate.require(current and json.loads(current[0])==intake)
            current_value=guard.qualified(b,issue)
            gate.require(current_value==value)
            gate.store(con,record)
        return record
