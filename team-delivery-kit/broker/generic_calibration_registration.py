"""Fetch native identities and immutable input-job facts before registration.

Controller-only. No operator/worker supplied approval objects are accepted by
register: it consumes a persisted intake, a real input job and exact native runs.
The producer/reviewer workflow must create those intents separately; missing
intents remain a prerequisite hold, never an implied approval.
"""
import hashlib
import json
import re

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
