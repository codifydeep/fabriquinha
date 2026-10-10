"""Controller-bound calibration data producer; not an execution approval.

The CTO supplies fixture bytes and adapter declarations, never hashes claiming
authority. Native identity, immutable copy facts and the approved recovery
contract provide all execution/scope bindings. Independent policy review and
real sandbox probes are still required by generic_calibration_registration.
"""
import hashlib
import json

from generic_harness_calibration import digest,relative,validate_policy
try:import generic_calibration_gate as gate
except ImportError:from broker import generic_calibration_gate as gate


def source_paths(body):
    return sorted({*('/evidence/candidate/'+m['path'] for m in body['modules']),
        *('/evidence/candidate/'+m['product_path'] for m in body['modules']),
        *('/evidence/previous/'+p for p in body['previous_methods'])})


def manifest(files):
    return json.dumps({'files':{name:dict(bytes=len(content.encode()),
        sha256=hashlib.sha256(content.encode()).hexdigest()) for name,content in files.items()}},sort_keys=True)


def bundle(body,value,route,prepared):
    gate.require(isinstance(body,dict) and set(body)=={'action','engine','modules','negatives',
        'previous_methods','controls','execution_authorized','delivery_approval'}
        and body['action']=='propose_calibration_bundle'
        and body['execution_authorized'] is False and body['delivery_approval'] is False)
    controls=body['controls']
    gate.require(isinstance(controls,dict) and 1<=len(controls)<=288)
    total=0
    for name,content in controls.items():
        relative(name)
        gate.require(name!='manifest.json' and isinstance(content,str))
        size=len(content.encode());total+=size
        gate.require(0<size<=65536 and total<=524288)
    control_manifest=manifest(controls)
    p=dict(version='generic_harness_calibration_v1',engine=body['engine'],
        source_task=value['source_task'],execution_sha256=digest(value),plan_sha256=value['plan_sha256'],
        candidate_manifest_sha256=prepared['manifest_sha256'],
        controls_manifest_sha256=hashlib.sha256(control_manifest.encode()).hexdigest(),
        criteria=sorted(value['criteria']),test_sha256=prepared['test_sha256'],
        previous_methods=body['previous_methods'],modules=body['modules'],negatives=body['negatives'])
    validate_policy(p,digest(p))
    fixtures={m['positive_fixture'] for m in p['modules']}|{n['fixture'] for n in p['negatives']}
    gate.require(set(controls)==fixtures
        and set(p['test_sha256'])==set(value['steps'][0]['editable_files'])==set(route['test_first_files'])
        and set(p['previous_methods'])==set(value['previous_new_test_delivery']['test_sha256']))
    return dict(operation='generic_calibration_proposal_bundle_v1',policy=p,policy_sha256=digest(p),
        controls=controls,controls_manifest=control_manifest,
        execution_authorized=False,delivery_approval=False)


def from_task(task,wakeup,value,route,prepared,reads):
    gate.require(task.get('status')=='completed' and task.get('agent_id')==route['cto']
        and task.get('issue_id')==route['issue_id'] and task.get('wakeup_id')==wakeup
        and len({route['author'],route['cto'],route['techlead']})==3)
    raw=(task.get('result') or {}).get('output')
    gate.require(isinstance(raw,str) and 1<=len(raw.encode())<=786432)
    body=json.loads(raw);record=bundle(body,value,route,prepared)
    paths=source_paths(body)
    for path in paths:
        observed=reads.get(path,{})
        gate.require(type(observed.get('lines')) is int and observed['lines']>0
            and observed['lines']==observed.get('total_lines'))
    record['producer']=dict(task_id=task['id'],actor=route['cto'],wakeup_id=wakeup,
        artifact_sha256=hashlib.sha256(raw.encode()).hexdigest(),read_evidence={p:reads[p] for p in paths})
    return record


def initialize(con):
    con.execute('CREATE TABLE IF NOT EXISTS generic_calibration_proposals('
        'issue_id TEXT,author_task TEXT,record TEXT,PRIMARY KEY(issue_id,author_task))')


def store(con,issue,author_task,record):
    """Internal only; collect supplies authenticated producer facts."""
    initialize(con)
    gate.require(record.get('operation')=='generic_calibration_proposal_bundle_v1'
        and record['policy_sha256']==digest(record['policy'])
        and record.get('execution_authorized') is False and record.get('delivery_approval') is False)
    validate_policy(record['policy'],record['policy_sha256'])
    old=con.execute('SELECT record FROM generic_calibration_proposals WHERE issue_id=? AND author_task=?',
        (issue,author_task)).fetchone()
    if old:gate.require(json.loads(old[0])==record);return record
    con.execute('INSERT INTO generic_calibration_proposals VALUES(?,?,?)',
        (issue,author_task,json.dumps(record,sort_keys=True)))
    return record


def collect(b,issue,author_task,producer_task,wakeup):
    """No caller-provided role, output, approval or source facts accepted."""
    try:import remediation_runtime_guard as guard,remediation_admission,technical_remediation_plan as plans,generic_calibration_registration as registration
    except ImportError:from broker import remediation_runtime_guard as guard,remediation_admission,technical_remediation_plan as plans,generic_calibration_registration as registration
    with b.LOCK:
        value=guard.qualified(b,issue)
        gate.require(value and value.get('amendment',{}).get('kind')=='inherited_frozen_suite')
        config,approved=remediation_admission.Effects(b).plan(value['source_task'])
        gate.require(approved['plan_sha256']==value['plan_sha256'])
        with b.db() as con:
            route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(issue,)).fetchone()[0])
            gate.require(route['cto']==config['cto'] and route['techlead']==config['reviewer']
                and route['author']==config['original_author'] and producer_task!=author_task)
            for tid,actor,mode in ((author_task,route['author'],'implementation'),(producer_task,route['cto'],'planning')):
                rows=con.execute('SELECT n.*,l.status FROM native_bindings n JOIN leases l USING(request_id) WHERE n.task_id=?',(tid,)).fetchall()
                gate.require(len(rows)==1 and rows[0]['status']=='closed' and rows[0]['issue_id']==issue
                    and rows[0]['agent_id']==actor and rows[0]['scope'].split(':')[-2:]==[mode,tid])
            copy=con.execute('SELECT identity,state FROM test_first_jobs WHERE job_key=?',(author_task+':copy',)).fetchone()
            gate.require(copy is not None);identity,state=map(json.loads,copy)
            gate.require(state.get('stage')=='complete')
            result=state['result'];raw=result['output']
            gate.require(type(result['exit_code']) is int and result['exit_code']==0 and result['approval'] is False
                and hashlib.sha256(raw.encode()).hexdigest()==result['output_sha256'])
            prepared=json.loads(raw)
        fx=plans.Effects(b)
        gate.require(fx.settings['agents'].get(route['cto'])=='planning'
            and fx.settings['agents'].get(route['author'])=='implementation')
        authored=fx.task(author_task,route['author'])
        gate.require(authored.get('status')=='completed' and authored.get('issue_id')==issue)
        task=fx.task(producer_task,route['cto'])
        record=from_task(task,wakeup,value,route,prepared,fx.reads(task))
        targets=[m for m in identity['payload']['HostConfig']['Mounts'] if m.get('Target')=='/snapshot']
        gate.require(len(targets)==1)
        volume=targets[0]['Source']
        tags=(b.docker('GET','/volumes/'+volume) or {}).get('Labels',{})
        gate.require(tags.get('delivery-kit.owner')==b.OWNER and tags.get('delivery-kit.test-first-task')==author_task)
        registration.copy_matches(dict(policy=record['policy'],context=dict(author_task=author_task,candidate_volume=volume)),identity,state)
        record['candidate_volume']=volume
        with b.db() as con:
            gate.require(guard.qualified(b,issue)==value)
            current=con.execute('SELECT identity,state FROM test_first_jobs WHERE job_key=?',(author_task+':copy',)).fetchone()
            gate.require(current and list(map(json.loads,current))==[identity,state])
            return store(con,issue,author_task,record)
