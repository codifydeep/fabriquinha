"""Opt-in non-executing typed decision submission at the controller proxy.

Only schema-valid model tool arguments become terminal JSON. No worker tool is
executed, no prose is mined, and no approval/permission is manufactured.
"""
import copy
import hashlib
import json
import re
from jsonschema import Draft202012Validator
from structured_response_contract import StructuredResponseRejected,_unique
import plan_length_feedback

NAME='submit_delivery_decision'
MARKER='DELIVERY_TYPED_DECISION_V1'
REVIEW_NAME='submit_test_review'
REVIEW_MARKER='DELIVERY_TYPED_REVIEW_V1'
TEST_DIAGNOSIS_MARKER='DELIVERY_TYPED_TEST_DIAGNOSIS_V1'
EVIDENCE_NAME='submit_deployment_evidence'
EVIDENCE_MARKER='DELIVERY_TYPED_DEPLOYMENT_EVIDENCE_V1'
VALIDATION_NAME='submit_deployment_validation_request'
DECOMPOSITION_MARKER='DELIVERY_TYPED_DECOMPOSITION_V1'
LENGTH_MARKER='DELIVERY_TECHNICAL_LENGTH_FEEDBACK_V1'
REVIEW_LENGTH_MARKER='DELIVERY_REVIEW_LENGTH_FEEDBACK_V1'
RECOVERY_NAME='submit_worker_recovery_request'
RECOVERY_MARKER='DELIVERY_TYPED_WORKER_RECOVERY_V1'
REMEDIATION_NAME='submit_remediation_contract'
from r3_incident_contract import NAME as R3_NAME
REMEDIATION_LENGTH_MARKER='DELIVERY_REMEDIATION_LENGTH_FEEDBACK_V1'
FORMAT_MARKER='DELIVERY_TECHNICAL_FORMAT_FEEDBACK_V1'


def diagnosis_actions(body):
    actions=['request_test_revision','escalate_cto']
    if any(m.get('role')=='user' and isinstance(m.get('content'),str)
            and re.search(r'^DELIVERY_REVIEW_RECONSIDERATION_V1$',m['content'],re.M)
            for m in body.get('messages',[])):
        actions.append('request_review_reconsideration')
    return actions


def format_feedback_enabled(body):
    """One opt-in format correction, restricted to nonauthorizing proposals."""
    if r3_length_feedback_enabled(body):return True
    if body.get('tool_choice') != {'type':'function','function':{'name':NAME}}:return False
    tools=body.get('tools',[])
    if len(tools)!=1:return False
    function=tools[0].get('function',{})
    spec=function.get('parameters',{});props=spec.get('properties',{})
    marked=any(m.get('role')=='user' and isinstance(m.get('content'),str)
        and re.search(r'^'+FORMAT_MARKER+r'$',m['content'],re.M) for m in body.get('messages',[]))
    if not marked:return False
    if set(props)=={'action','reason','optional_files','findings'}:
        if (function.get('strict') is not True or spec.get('additionalProperties') is not False
                or set(spec.get('required',[]))!=set(props)
                or props['action'].get('enum')!=diagnosis_actions(body)
                or props['optional_files'].get('maxItems')!=0
                or not any(m.get('role')=='user' and isinstance(m.get('content'),str)
                    and re.search(r'^'+TEST_DIAGNOSIS_MARKER+r'$',m['content'],re.M)
                    for m in body.get('messages',[]))):return False
        # Regenerate the controller's contract from its actual read evidence.
        # Foreign schemas, missing reads and permission expansion cannot opt in.
        from decision_schema import apply as decision_schema
        try:canonical=decision_schema(copy.deepcopy(body)).get('response_format',{}).get('json_schema',{}).get('schema')
        except (ValueError,KeyError,TypeError):return False
        return canonical==spec
    return (set(props)=={'action','reason','optional_files'}
        and bool(props['action'].get('enum'))
        and set(props['action']['enum'])<={'request_correction','request_test_revision','escalate_cto'}
        and props['optional_files'].get('maxItems')==0
        and marked)


def format_feedback_preflight(counter_path,execution_id,body):
    if not format_feedback_enabled(body):return
    from deterministic_read_dispatch import ledger
    with ledger(counter_path) as con:
        con.execute('CREATE TABLE IF NOT EXISTS technical_format_feedback(execution_id TEXT PRIMARY KEY,receipt TEXT)')
        if con.execute('SELECT 1 FROM technical_format_feedback WHERE execution_id=?',(execution_id,)).fetchone():
            raise StructuredResponseRejected('typed_format_feedback_consumed')


def claim_format_feedback(counter_path,execution_id,error,body,first_call):
    """Reject prose; ask the model afresh. Never parse, echo or accept prose."""
    if not format_feedback_enabled(body):return None
    shape=error.receipt['response_shape']
    r3=r3_length_feedback_enabled(body)
    malformed=error.category=='typed_arguments_invalid'
    if r3 or malformed:
        if (error.category!='typed_arguments_invalid' or shape.get('parsed') is not True
                or shape.get('terminal') is not True or shape.get('submissions')!=1
                or shape.get('expected_tool') is not True or shape.get('arguments_json_valid') is not False
                or shape.get('legacy_function_call') is not False or shape.get('content_shape')!='empty'
                or shape.get('arguments_rejection') in ('argument_type','argument_size')):return None
    elif (error.category not in ('typed_mixed_content','typed_nonterminal') or not shape['parsed']
            or shape['submissions']!=0 or shape['legacy_function_call']
            or shape['content_shape']!='nonempty' or not 1<=shape['content_chars']<=1200):return None
    if not isinstance(execution_id,str) or not re.fullmatch(r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}',execution_id):return None
    from deterministic_read_dispatch import ledger
    receipt=dict(operation='r3_json_format_feedback_v1' if r3 else
        'technical_json_format_feedback_v1' if malformed else 'technical_format_feedback_v1',first_call=first_call,
        rejected_upstream_sha256=error.receipt['upstream_sha256'],attempt_limit=1,
        worker_tool_executed=False,delivery_approval=False)
    with ledger(counter_path) as con:
        con.execute('CREATE TABLE IF NOT EXISTS technical_format_feedback(execution_id TEXT PRIMARY KEY,receipt TEXT)')
        if con.execute('SELECT 1 FROM technical_format_feedback WHERE execution_id=?',(execution_id,)).fetchone():return None
        con.execute('INSERT INTO technical_format_feedback VALUES (?,?)',(execution_id,json.dumps(receipt,sort_keys=True)))
    revised=copy.deepcopy(body)
    revised['messages'].append(dict(role='user',content=
        ('The previous tool submission was rejected: its arguments were not valid JSON. '
         if r3 or malformed else 'The previous response was rejected: prose without the required structured submission. ')+
        'Submit exactly one '+(R3_NAME if r3 else NAME)+' tool call with all fields of the unchanged schema. '
        'Do not add prose. No files, tests, permissions or delivery approval are authorized. '
        'This is the only format correction attempt.'))
    return revised


def remediation_length_feedback_enabled(body):
    if body.get('tool_choice')!={'type':'function','function':{'name':REMEDIATION_NAME}}:return False
    spec=body.get('tools',[{}])[0].get('function',{}).get('parameters',{})
    return ('decision' in spec.get('properties',{}) and any(m.get('role')=='user' and isinstance(m.get('content'),str)
        and re.search(r'^'+REMEDIATION_LENGTH_MARKER+r'$',m['content'],re.M) for m in body.get('messages',[])))


def length_feedback_enabled(body):
    return r3_length_feedback_enabled(body) or plan_length_feedback.enabled(body) or remediation_length_feedback_enabled(body) or review_length_feedback_enabled(body) or (body.get('tool_choice') in ({'type':'function','function':{'name':NAME}},
        {'type':'function','function':{'name':RECOVERY_NAME}}) and any(
        m.get('role')=='user' and isinstance(m.get('content'),str)
        and re.search(r'^'+LENGTH_MARKER+r'$',m['content'],re.M) for m in body.get('messages',[])))


def r3_length_feedback_enabled(body):
    if body.get('tool_choice')!={'type':'function','function':{'name':R3_NAME}}:return False
    tools=body.get('tools',[])
    if len(tools)!=1:return False
    schema=tools[0].get('function',{}).get('parameters',{})
    from r3_incident_contract import request_contract
    expected=request_contract(body)
    return expected is not None and schema==expected


def validate_r3_feedback_identity(body,decision):
    if not r3_length_feedback_enabled(body) or len(body.get('messages',[]))<2:return
    submitted,reply=body['messages'][-2:]
    if reply.get('role')!='tool' or not isinstance(reply.get('content'),str):return
    try:feedback=json.loads(reply['content'])
    except ValueError:return
    if feedback.get('operation')!='format_only_r3_reason_feedback_v1':return
    try:
        call=submitted['tool_calls'][0]
        if (submitted.get('role')!='assistant' or len(submitted['tool_calls'])!=1
                or call['id']!=reply.get('tool_call_id') or call['function']['name']!=R3_NAME):raise ValueError()
        previous=json.loads(call['function']['arguments'],object_pairs_hook=_unique)
        expected=copy.deepcopy(previous);expected['reason']=decision['reason']
        if expected!=decision:raise ValueError()
    except (ValueError,KeyError,IndexError,TypeError):
        raise StructuredResponseRejected('typed_r3_feedback_identity_drift') from None


def review_length_feedback_enabled(body):
    return body.get('tool_choice')=={'type':'function','function':{'name':REVIEW_NAME}} and any(
        m.get('role')=='user' and isinstance(m.get('content'),str)
        and re.search(r'^'+REVIEW_LENGTH_MARKER+r'$',m['content'],re.M) for m in body.get('messages',[]))


def review_length_violations(body, violations, decision, schema):
    """Only bounded prose/citation fields; never enums, snapshot IDs or paths."""
    if not review_length_feedback_enabled(body) or not 1<=len(violations)<=10:
        return None
    fields=[]
    validation_only=copy.deepcopy(decision)
    for violation in violations:
        # The action-specific branches repeat the root constraints. A root
        # length failure therefore also fails anyOf. Do not ignore that error:
        # validate the complete schema below after substituting only bounded
        # prose in a throwaway copy (never returned or accepted as a decision).
        if (violation.validator=='anyOf' and not list(violation.path)
                and list(violation.schema_path)==['anyOf']):continue
        path=list(violation.path)
        allowed=(path==['reason'] and violation.validator_value==1200 or
            len(path)==3 and path[0]=='findings' and type(path[1]) is int and 0<=path[1]<=2
            and path[2] in ('quote','expected','observed') and violation.validator_value==500)
        if (violation.validator!='maxLength' or not allowed or not isinstance(violation.instance,str)
                or not violation.validator_value<len(violation.instance)<=4000):return None
        fields.append(dict(path=path,maxLength=violation.validator_value,actualLength=len(violation.instance)))
        target=validation_only
        for part in path[:-1]:target=target[part]
        target[path[-1]]=violation.instance[:violation.validator_value]
    if not fields or not Draft202012Validator(schema).is_valid(validation_only):return None
    return fields


def validate_review_feedback_identity(body, decision):
    """A format repair cannot switch verdict, drop findings or change references."""
    if not review_length_feedback_enabled(body) or len(body.get('messages',[]))<2:return
    submitted,reply=body['messages'][-2:]
    if reply.get('role')!='tool' or not isinstance(reply.get('content'),str):return
    try:feedback=json.loads(reply['content'])
    except ValueError:return
    if not isinstance(feedback,dict) or feedback.get('operation')!='format_only_review_feedback_v1':return
    try:
        call=submitted['tool_calls'][0]
        if (submitted.get('role')!='assistant' or len(submitted['tool_calls'])!=1
                or call['id']!=reply.get('tool_call_id') or call['function']['name']!=REVIEW_NAME):
            raise ValueError()
        previous=json.loads(call['function']['arguments'],object_pairs_hook=_unique)
        expected=copy.deepcopy(previous)
        fields=feedback['fields']
        if not 1<=len(fields)<=10:raise ValueError()
        for field in fields:
            path=field['path']
            if path==['reason']:expected['reason']=decision['reason']
            elif (len(path)==3 and path[0]=='findings' and type(path[1]) is int
                    and 0<=path[1]<=2 and path[2] in ('quote','expected','observed')):
                expected['findings'][path[1]][path[2]]=decision['findings'][path[1]][path[2]]
            else:raise ValueError()
        if expected!=decision:raise ValueError()
    except (ValueError,KeyError,IndexError,TypeError):
        raise StructuredResponseRejected('typed_review_feedback_identity_drift') from None


def validate_remediation_feedback_identity(body,decision):
    if not remediation_length_feedback_enabled(body) or len(body.get('messages',[]))<2:return
    submitted,reply=body['messages'][-2:]
    if reply.get('role')!='tool' or not isinstance(reply.get('content'),str):return
    try:feedback=json.loads(reply['content'])
    except ValueError:return
    if feedback.get('operation')!='format_only_remediation_feedback_v1':return
    try:
        call=submitted['tool_calls'][0]
        if (submitted.get('role')!='assistant' or len(submitted['tool_calls'])!=1
                or call['id']!=reply.get('tool_call_id') or call['function']['name']!=REMEDIATION_NAME):raise ValueError()
        previous=json.loads(call['function']['arguments'],object_pairs_hook=_unique)
        expected=copy.deepcopy(previous);expected['reason']=decision['reason']
        if expected!=decision:raise ValueError()
    except (ValueError,KeyError,IndexError,TypeError):
        raise StructuredResponseRejected('typed_remediation_feedback_identity_drift') from None


def length_feedback_preflight(counter_path,execution_id,body):
    if not length_feedback_enabled(body):return
    from deterministic_read_dispatch import ledger
    with ledger(counter_path) as con:
        con.execute('CREATE TABLE IF NOT EXISTS technical_length_feedback(execution_id TEXT PRIMARY KEY,receipt TEXT)')
        if con.execute('SELECT 1 FROM technical_length_feedback WHERE execution_id=?',(execution_id,)).fetchone():
            raise StructuredResponseRejected('typed_length_feedback_consumed')


def claim_length_feedback(counter_path,execution_id,error,body,first_call):
    feedback=getattr(error,'length_feedback',None)
    if not feedback or not length_feedback_enabled(body):return None
    if not isinstance(execution_id,str) or not re.fullmatch(r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}',execution_id):return None
    from deterministic_read_dispatch import ledger
    receipt={'operation':'review_length_feedback_v1' if review_length_feedback_enabled(body) else 'technical_length_feedback_v1','first_call':first_call,
        'rejected_upstream_sha256':error.receipt['upstream_sha256'],'attempt_limit':1,
        'worker_tool_executed':False,'delivery_approval':False}
    if review_length_feedback_enabled(body):
        receipt['review_acceptance_by_proxy']=False
        receipt['manifest_sha256']=body['tools'][0]['function']['parameters']['properties']['manifest_sha256']['enum'][0]
    if remediation_length_feedback_enabled(body):
        receipt.update(operation='remediation_review_length_feedback_v1',plan_acceptance_by_proxy=False,
            plan_sha256=body['tools'][0]['function']['parameters']['properties']['plan_sha256']['enum'][0])
    if plan_length_feedback.enabled(body):
        receipt.update(operation='remediation_plan_length_feedback_v1',plan_acceptance_by_proxy=False,
            evidence_sha256=body['tools'][0]['function']['parameters']['properties']['evidence_sha256']['enum'][0])
    if r3_length_feedback_enabled(body):
        receipt.update(operation='r3_reason_length_feedback_v1',execution_authorized=False,
            evidence_sha256=body['tools'][0]['function']['parameters']['properties']['evidence_sha256']['enum'][0])
    with ledger(counter_path) as con:
        con.execute('CREATE TABLE IF NOT EXISTS technical_length_feedback(execution_id TEXT PRIMARY KEY,receipt TEXT)')
        if con.execute('SELECT 1 FROM technical_length_feedback WHERE execution_id=?',(execution_id,)).fetchone():return None
        con.execute('INSERT INTO technical_length_feedback VALUES (?,?)',(execution_id,json.dumps(receipt,sort_keys=True)))
    revised=copy.deepcopy(body);revised['messages'].extend(feedback)
    return revised


def apply(body):
    from product_scope_contract import request as scope_request
    scope=scope_request(body)
    if scope is not None:
        if not body.get('response_format') and body.get('tool_choice')=={'type':'function','function':{'name':'read_file'}}:
            return body
        spec=body.get('response_format',{}).get('json_schema',{})
        if spec.get('name')!='delivery_product_scope_v1' or spec.get('strict') is not True or spec.get('schema')!=scope[1]:
            raise ValueError('exact nonauthorizing scope schema required')
        result=copy.deepcopy(body);result.pop('response_format',None);result.pop('parallel_tool_calls',None)
        result['tools']=[dict(type='function',function=dict(name=NAME,strict=True,
            description='Submit scope proposal or independent review data only; no operation executes.',parameters=scope[1]))]
        result['tool_choice']=dict(type='function',function=dict(name=NAME))
        result['messages'].append(dict(role='system',content='Call '+NAME+' exactly once with schema-valid arguments. '
            'No prose or simulated calls. This is not an edit grant, test waiver, delivery approval or release approval.'))
        return result
    from r3_incident_contract import request_contract
    incident = request_contract(body)
    if incident is not None:
        spec=body.get('response_format',{}).get('json_schema',{})
        if (spec.get('name')!='delivery_r3_incident_v1' or spec.get('strict') is not True
                or spec.get('schema')!=incident):
            raise ValueError('exact nonauthorizing R3 schema required')
        result=copy.deepcopy(body);result.pop('response_format',None);result.pop('parallel_tool_calls',None)
        result['tools']=[dict(type='function',function=dict(name=R3_NAME,strict=True,
            description='Submit technical diagnosis or review data only. No worker operation executes.',parameters=incident))]
        result['tool_choice']=dict(type='function',function=dict(name=R3_NAME))
        result['messages'].append(dict(role='system',content='Call '+R3_NAME+' exactly once with actual schema-valid arguments. '
            'reason must be one actionable sentence, target280characters, hard limit600characters. '
            'No prose or simulated calls. Reference all verified facts. This submission grants no execution, merge, '
            'test waiver or release authority; execution_authorized and release_homologated remain false.'))
        return result
    remediations={(kind,sha) for m in body.get('messages',[]) if m.get('role')=='user' and isinstance(m.get('content'),str)
        for kind,sha in re.findall(r'^DELIVERY_TYPED_REMEDIATION_V1:(plan|review):([a-f0-9]{64})$',m['content'],re.M)}
    if remediations:
        if len(remediations)!=1:raise ValueError('one nonexecuting remediation contract required')
        if not body.get('response_format') and body.get('tool_choice')=={'type':'function','function':{'name':'read_file'}}:
            return body
        kind,sha=next(iter(remediations))
        notes='\n'.join(m['content'] for m in body['messages'] if m.get('role')=='user' and isinstance(m.get('content'),str))
        contracts=set(re.findall(r'^DELIVERY_REMEDIATION_(PLAN|REVIEW)_V1:([a-f0-9]{64})$',notes,re.M))
        if contracts!={(kind.upper(),sha)} or re.search(r'^DELIVERY_TYPED_(?:DECISION|REVIEW|DECOMPOSITION|DEPLOYMENT|WORK_PROPOSAL|RECOVERY)',notes,re.M):
            raise ValueError('isolated matching remediation binding required')
        from remediation_plan_contract import schema as remediation_schema
        ids=sorted({c for m in body['messages'] if m.get('role')=='user' and isinstance(m.get('content'),str)
            for c in re.findall(r'^DELIVERY_REMEDIATION_CRITERION:(A[0-9]{2})$',m['content'],re.M)})
        spec=body.get('response_format',{}).get('json_schema',{})
        expected=remediation_schema(kind,sha,ids)
        if kind=='plan' and not 1<=len(ids)<=32:
            raise ValueError('bounded complete criterion identities required')
        if (spec.get('name')!='delivery_decision_v1' or spec.get('strict') is not True
                or spec.get('schema')!=expected):
            raise ValueError('exact nonauthorizing remediation schema required')
        result=copy.deepcopy(body);result.pop('response_format',None);result.pop('parallel_tool_calls',None)
        result['tools']=[dict(type='function',function=dict(name=REMEDIATION_NAME,strict=True,
            description='Submit only recovery plan/review data. No worker tool executes and no delivery is approved.',parameters=expected))]
        result['tool_choice']=dict(type='function',function=dict(name=REMEDIATION_NAME))
        result['messages'].append(dict(role='system',content='Call '+REMEDIATION_NAME+' exactly once with actual schema-valid arguments. '
            'No prose, fences, JSON text or simulated call. Keep reason within600 characters. '
            'All execution_authorized/release_homologated flags remain false.'))
        return result
    recoveries={v for m in body.get('messages',[]) if m.get('role')=='user' and isinstance(m.get('content'),str)
        for v in re.findall(r'^'+RECOVERY_MARKER+r':([a-f0-9]{64})$',m['content'],re.M)}
    if recoveries:
        notes='\n'.join(m['content'] for m in body['messages'] if m.get('role')=='user' and isinstance(m.get('content'),str))
        spec=body.get('response_format',{}).get('json_schema',{})
        expected={'type':'object','properties':{
            'action':{'type':'string','enum':['retry_author','escalate_cto']},
            'reason':{'type':'string','minLength':1,'maxLength':1200},
            'optional_files':{'type':'array','items':{'type':'string'},'maxItems':0}},
            'required':['action','reason','optional_files'],'additionalProperties':False}
        if (len(recoveries)!=1 or spec.get('name')!='delivery_decision_v1' or spec.get('strict') is not True
                or spec.get('schema')!=expected or any(not re.search(r'^'+mark+r'$',notes,re.M) for mark in
                    ('DELIVERY_STRUCTURED_DECISION_V1:technical','DELIVERY_EXECUTION_REPAIR_V1','DELIVERY_WORKER_INTERRUPTION_RECOVERY_V1'))
                or re.search(r'^DELIVERY_TYPED_(?:DECISION|REVIEW|DECOMPOSITION|DEPLOYMENT|WORK_PROPOSAL)',notes,re.M)):
            raise ValueError('exact isolated worker recovery request contract required')
        result=copy.deepcopy(body);result.pop('response_format',None);result.pop('parallel_tool_calls',None)
        result['tools']=[{'type':'function','function':{'name':RECOVERY_NAME,'strict':True,
            'description':'Submit recovery-request data only. This tool never runs a worker or grants retry authority; the controller checks independent CTO identity, durable evidence and the unused allowance.',
            'parameters':expected}}]
        result['tool_choice']={'type':'function','function':{'name':RECOVERY_NAME}}
        result['messages'].append({'role':'user','content':LENGTH_MARKER+'\n'})
        result['messages'].append({'role':'system','content':'Call '+RECOVERY_NAME+' exactly once with actual arguments. '
            'No prose or simulated tool call. reason target420characters, limit1200. No operation executes; '
            'no Red, tests, worker restart, merge or approval is implied.'})
        return result
    from work_proposal_contract import schema as work_schema
    proposals={v for m in body.get('messages',[]) if m.get('role')=='user' and isinstance(m.get('content'),str)
        for v in re.findall(r'^DELIVERY_TYPED_WORK_PROPOSAL_V1:([a-f0-9]{64})$',m['content'],re.M)}
    if proposals:
        if len(proposals)!=1:raise ValueError('one work proposal digest required')
        sha=proposals.pop();spec=body.get('response_format',{}).get('json_schema',{})
        if spec.get('name')!='delivery_work_proposal_v1' or spec.get('strict') is not True or spec.get('schema')!=work_schema(sha):
            raise ValueError('exact non-authorizing work proposal schema required')
        result=copy.deepcopy(body);result.pop('response_format',None)
        result['tools']=[{'type':'function','function':{'name':NAME,'strict':True,
            'description':'Submit work proposal data only; no task executes and no release is approved.', 'parameters':spec['schema']}}]
        result['tool_choice']={'type':'function','function':{'name':NAME}}
        return result
    validations={v for m in body.get('messages',[]) if m.get('role')=='user' and isinstance(m.get('content'),str)
        for v in re.findall(r'^DELIVERY_TYPED_DEPLOYMENT_VALIDATION_V1:([a-f0-9]{64})$',m['content'],re.M)}
    if validations:
        from decision_schema import validation_schema
        if len(validations)!=1 or any(re.search(r'^DELIVERY_TYPED_(?:DECISION|REVIEW|DECOMPOSITION|DEPLOYMENT_EVIDENCE)_V1',
                str(m.get('content','')),re.M) for m in body['messages']):raise ValueError('conflicting typed validation contracts')
        sha=next(iter(validations));spec=body.get('response_format',{}).get('json_schema',{})
        if (spec.get('name')!='delivery_deployment_validation_v1' or spec.get('strict') is not True
                or spec.get('schema')!=validation_schema(sha)):raise ValueError('fixed validation request schema required')
        result=copy.deepcopy(body);result.pop('response_format',None);result.pop('parallel_tool_calls',None)
        result['tools']=[{'type':'function','function':{'name':VALIDATION_NAME,'strict':True,
            'description':'Request one fixed QA operation. No worker tool executes; controller validates caller and scope.',
            'parameters':spec['schema']}}]
        result['tool_choice']={'type':'function','function':{'name':VALIDATION_NAME}}
        result['messages'].append({'role':'system','content':'Call '+VALIDATION_NAME+' once. Use actual tool arguments, '
            'not text simulation. reason <=600 characters. This only requests QA; no test has executed yet.'})
        return result
    evidence={sha for m in body.get('messages',[]) if m.get('role')=='user' and isinstance(m.get('content'),str)
        for sha in re.findall(r'^'+EVIDENCE_MARKER+r':([a-f0-9]{64})$',m['content'],re.M)}
    if evidence:
        if len(evidence)!=1 or any(re.search(r'^DELIVERY_TYPED_(?:DECISION|REVIEW|DECOMPOSITION)_V1',
                str(m.get('content','')),re.M) for m in body.get('messages',[])):
            raise ValueError('conflicting typed evidence contracts')
        sha=next(iter(evidence));spec=body.get('response_format',{}).get('json_schema',{})
        schema=spec.get('schema',{});props=schema.get('properties',{})
        if (spec.get('name')!='delivery_deployment_evidence_v1' or spec.get('strict') is not True
                or props.get('evidence_sha256',{}).get('enum')!=[sha]
                or props.get('reason',{}).get('maxLength')!=1200
                or props.get('decision',{}).get('enum')!=['ACCEPT_EVIDENCE','REQUEST_CHANGES']
                or any(props.get(k,{}).get('enum')!=[False] for k in
                    ('release_homologated','product_admission_authorized','historical_tdd_red'))
                or schema.get('additionalProperties') is not False
                or set(schema.get('required',[]))!=set(props)):
            raise ValueError('exact non-authorizing deployment evidence schema required')
        result=copy.deepcopy(body);result.pop('response_format',None);result.pop('parallel_tool_calls',None)
        result['tools']=[{'type':'function','function':{'name':EVIDENCE_NAME,'strict':True,
            'description':'Submit evidence assessment data, never execute a worker tool or approve a release.',
            'parameters':schema}}]
        result['tool_choice']={'type':'function','function':{'name':EVIDENCE_NAME}}
        result['messages'].append({'role':'system','content':'Call '+EVIDENCE_NAME+' exactly once with schema-valid arguments. '
            'No prose, fences or tool-result simulation. reason target <=600 characters. '
            'This data submission does not execute a tool, independently run QA or approve a release.'})
        return result
    decomposition=any(m.get('role')=='user' and isinstance(m.get('content'),str)
        and re.search(r'^'+DECOMPOSITION_MARKER+r'$',m['content'],re.M) for m in body.get('messages',[]))
    marked=any(m.get('role')=='user' and isinstance(m.get('content'),str)
        and re.search(r'^'+MARKER+r'$',m['content'],re.M) for m in body.get('messages',[]))
    reviews={sha for m in body.get('messages',[]) if m.get('role')=='user' and isinstance(m.get('content'),str)
        for sha in re.findall(r'^'+REVIEW_MARKER+r':([a-f0-9]{64})$',m['content'],re.M)}
    if not marked and not reviews and not decomposition:return body
    if len(reviews)>1 or (marked and reviews) or (decomposition and (marked or reviews)):
        raise ValueError('conflicting typed contracts')
    review=next(iter(reviews)) if reviews else None
    if review:
        modes={sha for m in body.get('messages',[]) if m.get('role')=='user' and isinstance(m.get('content'),str)
            for sha in re.findall(r'^DELIVERY_STRUCTURED_DECISION_V1:test_review:([a-f0-9]{64})$',m['content'],re.M)}
        if modes!={review}:raise ValueError('same snapshot review contract required')
    fmt=body.get('response_format',{})
    if not fmt and body.get('tool_choice')=={'type':'function','function':{'name':'read_file'}}:
        return body  # mandatory inspection is never replaced by a verdict tool
    spec=fmt.get('json_schema',{})
    if fmt.get('type')!='json_schema' or spec.get('name')!='delivery_decision_v1':
        raise ValueError('typed decision requires completed technical decision schema')
    schema=spec['schema']
    if review:
        props=schema.get('properties',{})
        if (set(props) not in ({'action','reason','optional_files','manifest_sha256'},
                {'action','reason','optional_files','manifest_sha256','findings'})
                or props['action'].get('enum')!=['approve_test_revision','reject_test_revision']
                or props['manifest_sha256'].get('enum')!=[review]
                or props['optional_files'].get('maxItems')!=0):
            raise ValueError('immutable test review schema required')
    elif decomposition:
        props=schema.get('properties',{})
        if (set(props)!={'action','reason','optional_files','units'}
                or props['action'].get('enum')!=['propose_test_decomposition','escalate_cto']
                or props['optional_files'].get('maxItems')!=0
                or set(props['units'].get('items',{}).get('properties',{}))!=
                    {'id','depends_on','criteria','objective'}):
            raise ValueError('non-executing decomposition schema required')
    elif any(m.get('role')=='user' and isinstance(m.get('content'),str)
             and re.search(r'^'+TEST_DIAGNOSIS_MARKER+r'$',m['content'],re.M) for m in body['messages']):
        props=schema.get('properties',{})
        if (set(props)!={'action','reason','optional_files','findings'}
                or props['action'].get('enum')!=diagnosis_actions(body)
                or props['optional_files'].get('maxItems')!=0
                or not props['findings'].get('items',{}).get('anyOf')):
            raise ValueError('observed non-approving test diagnosis contract required')
    elif (set(schema.get('properties',{}))!={'action','reason','optional_files'}
            or not set(schema['properties']['action'].get('enum',[]))<=
                {'request_correction','request_test_revision','escalate_cto'}):
        raise ValueError('typed submission cannot grant review or execution authority')
    name=REVIEW_NAME if review else NAME
    result=copy.deepcopy(body)
    result.pop('response_format',None);result.pop('parallel_tool_calls',None)
    result['tools']=[{'type':'function','function':{'name':name,'strict':True,
        'description':'Submit schema-valid decision data only; the controller independently validates identity, reads and snapshot before accepting any verdict.',
        'parameters':schema}}]
    result['tool_choice']={'type':'function','function':{'name':name}}
    execution_diagnosis = any(m.get('role') == 'user' and isinstance(m.get('content'), str)
        and re.search(r'^DELIVERY_EXECUTION_DIAGNOSIS_V1$', m['content'], re.M)
        for m in body.get('messages', []))
    if (execution_diagnosis and name == NAME
            and schema['properties']['action'].get('enum') == ['escalate_cto']
            and schema['properties']['reason'].get('maxLength') == 1200):
        # At most one format-only response per execution, enforced by the
        # existing durable length-feedback ledger. No action/schema is broadened.
        result['messages'].append({'role':'user', 'content':LENGTH_MARKER + '\n'})
    if name==REVIEW_NAME:
        result['messages'].append({'role':'user','content':REVIEW_LENGTH_MARKER+'\n'})
    result['messages'].append({'role':'system','content':
        'TYPED DECISION PHASE: call '+name+' exactly once with every required schema field. '
        'Use actual tool arguments, not prose or a Markdown code block. This is a non-executing data submission. '
        'No approval, file change, test execution, merge, budget exception or release completion is implied. '
        'reason must fit the schema limit. Prefer one concise concrete recommendation.'})
    return result


def selected(body):
    return body.get('tool_choice') in ({'type':'function','function':{'name':NAME}},
                                     {'type':'function','function':{'name':REVIEW_NAME}},
                                     {'type':'function','function':{'name':EVIDENCE_NAME}},
                                     {'type':'function','function':{'name':VALIDATION_NAME}},
                                     {'type':'function','function':{'name':RECOVERY_NAME}},
                                     {'type':'function','function':{'name':REMEDIATION_NAME}},
                                     {'type':'function','function':{'name':R3_NAME}})


def normalize_technical_padding(body,data,media_type):
    """Normalize <=16 ASCII formatting chars; never prose, review or arguments."""
    if body.get('tool_choice') not in ({'type':'function','function':{'name':NAME}},
            {'type':'function','function':{'name':RECOVERY_NAME}},
            {'type':'function','function':{'name':REMEDIATION_NAME}}):return data,None
    return _normalize_ascii_padding(data,media_type,'technical_ascii_padding_normalization_v1')


def normalize_review_padding(body,data,media_type):
    """Opt-in transport formatting only; does not accept a review or alter args."""
    if body.get('tool_choice')!={'type':'function','function':{'name':REVIEW_NAME}}:return data,None
    try:
        props=body['tools'][0]['function']['parameters']['properties']
        snapshots=props['manifest_sha256']['enum']
        if (props['action']['enum']!=['approve_test_revision','reject_test_revision']
                or len(snapshots)!=1 or not re.fullmatch('[a-f0-9]{64}',snapshots[0])):
            return data,None
    except (KeyError,TypeError,IndexError):return data,None
    normalized,receipt=_normalize_ascii_padding(data,media_type,'review_ascii_padding_normalization_v1')
    if receipt:receipt.update(manifest_sha256=snapshots[0],review_acceptance_by_proxy=False)
    return normalized,receipt


def normalize_evidence_padding(body,data,media_type):
    if body.get('tool_choice')!={'type':'function','function':{'name':EVIDENCE_NAME}}:return data,None
    try:
        props=body['tools'][0]['function']['parameters']['properties']
        if any(props[k].get('enum')!=[False] for k in
                ('release_homologated','product_admission_authorized','historical_tdd_red')):return data,None
    except (KeyError,TypeError,IndexError):return data,None
    return _normalize_ascii_padding(data,media_type,'deployment_evidence_ascii_padding_v1')


def normalize_validation_padding(body,data,media_type):
    if body.get('tool_choice')!={'type':'function','function':{'name':VALIDATION_NAME}}:return data,None
    try:
        props=body['tools'][0]['function']['parameters']['properties']
        if props['operation'].get('enum')!=['run_fixed_deployment_qa']:return data,None
        if any(props[k].get('enum')!=[False] for k in
                ('release_homologated','product_admission_authorized')):return data,None
    except (KeyError,TypeError,IndexError):return data,None
    return _normalize_ascii_padding(data,media_type,'deployment_validation_ascii_padding_v1')


def _normalize_ascii_padding(data,media_type,operation):
    original=data;count=0
    def clean(message,terminal_seen=False):
        nonlocal count
        content=message.get('content')
        if content in (None,''):return
        if (terminal_seen or not isinstance(content,str) or re.fullmatch(r'[ \t\r\n]+',content) is None
                or count+len(content)>16):raise ValueError()
        count+=len(content);message['content']=''
    try:
        if media_type.startswith('text/event-stream'):
            lines=data.decode().splitlines();finished=False;done=False
            for index,line in enumerate(lines):
                if not line.startswith('data:'):continue
                raw=line[5:].strip()
                if raw=='[DONE]':done=True;continue
                frame=json.loads(raw,object_pairs_hook=_unique)
                choices=frame.get('choices',[])
                if done:raise ValueError()
                if not choices:continue
                if len(choices)!=1:raise ValueError()
                entry=choices[0];delta=entry.get('delta',{})
                clean(delta,finished)
                if entry.get('finish_reason') is not None:finished=True
                lines[index]='data: '+json.dumps(frame,separators=(',',':'))
            normalized=('\n'.join(lines)+'\n').encode()
        else:
            frame=json.loads(data,object_pairs_hook=_unique)
            if len(frame.get('choices',[]))!=1:raise ValueError()
            clean(frame['choices'][0]['message'])
            normalized=json.dumps(frame,separators=(',',':')).encode()
        if not count:return original,None
        return normalized,dict(operation=operation,
            original_upstream_sha256=hashlib.sha256(original).hexdigest(),
            normalized_upstream_sha256=hashlib.sha256(normalized).hexdigest(),padding_chars=count,
            model_arguments_unchanged=True,worker_tool_executed=False,delivery_approval=False)
    except Exception:return original,None


def response_shape(body,data,media_type):
    """Diagnostic only: never accept a decision or export model-supplied text."""
    result=dict(version=1,parsed=False,terminal=False,submissions=0,
                content_shape='empty',content_chars=0,legacy_function_call=False,
                expected_tool=False,arguments_json_valid=None,arguments_schema_valid=None,
                arguments_chars=None,arguments_rejection=None)
    try:
        contents=[];calls={};finished=False;done=False
        if media_type.startswith('text/event-stream'):
            for line in data.decode().splitlines():
                if not line.startswith('data:'):continue
                raw=line[5:].strip()
                if raw=='[DONE]':done=True;continue
                frame=json.loads(raw,object_pairs_hook=_unique)
                if frame.get('error') or done:raise ValueError()
                choices=frame.get('choices',[])
                if not choices:continue
                if len(choices)!=1:raise ValueError()
                entry=choices[0];delta=entry.get('delta',{})
                contents.append(delta.get('content'))
                result['legacy_function_call']|=bool(delta.get('function_call'))
                for call in delta.get('tool_calls',[]):
                    key=call.get('index',0);fn=call.get('function',{})
                    pair=calls.setdefault(key,['',''])
                    pair[0]+=fn.get('name') or '';pair[1]+=fn.get('arguments') or ''
                if entry.get('finish_reason') is not None:
                    finished=entry['finish_reason']=='tool_calls'
            result['terminal']=finished and done
        else:
            frame=json.loads(data,object_pairs_hook=_unique)
            if frame.get('error') or len(frame.get('choices',[]))!=1:raise ValueError()
            entry=frame['choices'][0];message=entry['message']
            result['terminal']=entry.get('finish_reason')=='tool_calls'
            contents.append(message.get('content'))
            result['legacy_function_call']=bool(message.get('function_call'))
            for index,call in enumerate(message.get('tool_calls',[])):
                fn=call.get('function',{});calls[index]=[fn.get('name'),fn.get('arguments')]
        result['parsed']=True;result['submissions']=len(calls)
        if any(c is not None and not isinstance(c,str) for c in contents):
            result['content_shape']='invalid_type'
        else:
            text=''.join(c or '' for c in contents);result['content_chars']=len(text)
            result['content_shape']='nonempty' if text.strip() else ('whitespace_only' if text else 'empty')
        if len(calls)==1:
            name,arguments=next(iter(calls.values()))
            result['expected_tool']=name==body['tool_choice']['function']['name']
            result['arguments_json_valid']=False
            result['arguments_chars']=len(arguments) if isinstance(arguments,str) else None
            if not isinstance(arguments,str):result['arguments_rejection']='argument_type'
            elif not 1<=len(arguments)<=5000:result['arguments_rejection']='argument_size'
            if isinstance(arguments,str) and 1<=len(arguments)<=5000:
                try:
                    decision=json.loads(arguments,object_pairs_hook=_unique,
                        parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
                    result['arguments_json_valid']=True
                    result['arguments_schema_valid']=Draft202012Validator(
                        body['tools'][0]['function']['parameters']).is_valid(decision)
                except json.JSONDecodeError:result['arguments_rejection']='json_syntax'
                except ValueError:result['arguments_rejection']='json_policy'
                except Exception:result['arguments_rejection']='validation_error'
        return result
    except Exception:return result


def constraint_diagnostic(violations,schema,data):
    """Fixed keywords only, including nested anyOf errors; never instance data."""
    allowed={'type','enum','const','required','additionalProperties','minLength',
             'maxLength','minItems','maxItems','uniqueItems','pattern',
             'minimum','maximum','anyOf','oneOf','allOf','not'}
    violations=list(violations)
    pending=list(violations);constraints=set();locations=set()
    # Only controller-defined labels, never arbitrary instance/schema paths,
    # enum values, source quotes, expected strings or validator messages.
    labels={('action','enum'):'action_selection',
        ('manifest_sha256','enum'):'snapshot_selection',
        ('optional_files','maxItems'):'optional_file_count',
        ('findings','maxItems'):'finding_count',
        ('findings','minItems'):'finding_count'}
    for error in violations:
        path=list(error.path)
        if len(path)==1:
            label=labels.get((path[0],error.validator))
            if label:locations.add(label)
        elif (len(path)==2 and path[0]=='findings' and type(path[1]) is int
                and 0<=path[1]<64 and error.validator=='anyOf'):
            locations.add('finding_location_selection')
    while pending:
        error=pending.pop()
        constraints.add(error.validator if error.validator in allowed else 'other')
        pending.extend(error.context)
    return dict(version='typed-constraint-v1',constraints=sorted(constraints),
        root_constraints=sorted({e.validator if e.validator in allowed else 'other' for e in violations}),
        locations=sorted(locations),
        schema_sha256=hashlib.sha256(json.dumps(schema,sort_keys=True).encode()).hexdigest(),
        upstream_sha256=hashlib.sha256(data).hexdigest())


def translate(body,data,media_type):
    if not selected(body):return data,media_type,None
    phase='envelope';diagnostic=None
    def reject(category):
        raise StructuredResponseRejected('typed_'+category)
    try:
        schema=body['tools'][0]['function']['parameters']
        if media_type.startswith('text/event-stream'):
            name='';arguments='';finished=False;done=False
            for line in data.decode().splitlines():
                if not line.startswith('data:'):continue
                raw=line[5:].strip()
                if raw=='[DONE]':
                    if done or not finished:reject('stream_incomplete')
                    done=True;continue
                if done:reject('data_after_terminal')
                frame=json.loads(raw,object_pairs_hook=_unique)
                if frame.get('error'):reject('provider_error')
                choices=frame.get('choices',[])
                if not choices:continue
                if len(choices)!=1 or choices[0].get('index',0)!=0:reject('multiple_choices')
                entry=choices[0];delta=entry.get('delta',{})
                if delta.get('content') or delta.get('function_call'):reject('mixed_content')
                calls=delta.get('tool_calls',[])
                if calls:
                    if finished or len(calls)!=1 or calls[0].get('index',0)!=0:reject('multiple_submissions')
                    call=calls[0]
                    if call.get('type','function')!='function':reject('unexpected_tool_type')
                    fn=call.get('function',{})
                    name+=fn.get('name') or '';arguments+=fn.get('arguments') or ''
                if entry.get('finish_reason') is not None:
                    if entry['finish_reason']!='tool_calls':reject('nonterminal')
                    # OpenRouter may repeat an empty terminal marker before
                    # DONE. Accept only that idempotent transport acknowledgement;
                    # never accept more arguments/content or a different finish.
                    if finished and (set(delta)-{'content','tool_calls','function_call','role'} or
                            delta.get('role') not in (None,'assistant') or
                            any(value not in (None,'',[]) for key,value in delta.items() if key!='role')):
                        reject('terminal_payload_repeated')
                    finished=True
            if not finished or not done:reject('stream_incomplete')
        else:
            envelope=json.loads(data,object_pairs_hook=_unique);choices=envelope.get('choices',[])
            if envelope.get('error'):reject('provider_error')
            if len(choices)!=1:reject('multiple_choices')
            if choices[0].get('finish_reason')!='tool_calls':reject('nonterminal')
            message=choices[0]['message'];calls=message.get('tool_calls',[])
            if message.get('content') or message.get('function_call'):reject('mixed_content')
            if len(calls)!=1:reject('multiple_submissions')
            call=calls[0]
            if call.get('type','function')!='function':reject('unexpected_tool_type')
            name=call['function']['name'];arguments=call['function']['arguments']
        if name!=body['tool_choice']['function']['name']:reject('wrong_tool_name')
        if not isinstance(arguments,str) or not 1<=len(arguments)<=5000:reject('argument_type_or_size')
        phase='arguments'
        decision=json.loads(arguments,object_pairs_hook=_unique,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')))
        violations=list(Draft202012Validator(schema).iter_errors(decision))
        if violations:
            diagnostic=constraint_diagnostic(violations,schema,data)
            if (r3_length_feedback_enabled(body) and len(violations)==1
                    and violations[0].validator=='maxLength' and list(violations[0].path)==['reason']
                    and isinstance(decision.get('reason'),str) and 600<len(decision['reason'])<=4000):
                error=StructuredResponseRejected('typed_schema_maxLength')
                identity='format_'+hashlib.sha256(data).hexdigest()[:24]
                error.length_feedback=[dict(role='assistant',content=None,tool_calls=[dict(id=identity,type='function',
                    function=dict(name=name,arguments=arguments))]),dict(role='tool',tool_call_id=identity,
                    content=json.dumps(dict(operation='format_only_r3_reason_feedback_v1',field='reason',maxLength=600,
                    actualLength=len(decision['reason']),worker_tool_executed=False,execution_authorized=False,
                    instruction='Submit NEW valid arguments once. Condense only reason to one actionable sentence, target280characters. '
                    'Keep every other field identical, including action/decision, experiment, evidence/proposal hashes, fact_ids and false flags. '
                    'No decision was accepted or operation authorized.')))]
                raise error
            plan_feedback=plan_length_feedback.feedback(body,violations,decision,schema,arguments,data)
            if plan_feedback:
                error=StructuredResponseRejected('typed_schema_maxLength');error.length_feedback=plan_feedback
                raise error
            if (remediation_length_feedback_enabled(body) and len(violations)==1
                    and violations[0].validator=='maxLength' and list(violations[0].path)==['reason']
                    and schema['properties']['reason'].get('maxLength')==600
                    and isinstance(decision.get('reason'),str) and 600<len(decision['reason'])<=4000):
                error=StructuredResponseRejected('typed_schema_maxLength')
                identity='format_'+hashlib.sha256(data).hexdigest()[:24]
                error.length_feedback=[dict(role='assistant',content=None,tool_calls=[dict(id=identity,type='function',
                    function=dict(name=name,arguments=arguments))]),dict(role='tool',tool_call_id=identity,
                    content=json.dumps(dict(operation='format_only_remediation_feedback_v1',field='reason',maxLength=600,
                    actualLength=len(decision['reason']),worker_tool_executed=False,plan_acceptance_by_proxy=False,
                    instruction='Submit NEW valid arguments once. Condense only reason, target300characters. '
                    'Preserve decision, evidence_sha256, plan_sha256 and all flags exactly. No action was executed or approved.')))]
                raise error
            if (length_feedback_enabled(body) and len(violations)==1
                    and violations[0].validator=='maxLength' and list(violations[0].path)==['reason']
                    and schema['properties']['reason'].get('maxLength')==1200
                    and 1200<len(decision['reason'])<=4000
                    and set(decision)=={'action','reason','optional_files'}):
                error=StructuredResponseRejected('typed_schema_maxLength')
                identity='format_'+hashlib.sha256(data).hexdigest()[:24]
                error.length_feedback=[{'role':'assistant','content':None,'tool_calls':[{
                    'id':identity,'type':'function','function':{'name':name,'arguments':arguments}}]},
                    {'role':'tool','tool_call_id':identity,'content':json.dumps({
                        'validation_response':'rejected_schema','field':'reason','maxLength':1200,
                        'actualLength':len(decision['reason']),'worker_tool_executed':False,
                        'instruction':'Submit NEW valid arguments once. Condense reason to one actionable sentence, target420characters. No background or policy narration. Preserve factual classification and required fields. Nothing was executed or approved.'})}]
                raise error
            fields=review_length_violations(body,violations,decision,schema)
            if fields:
                error=StructuredResponseRejected('typed_schema_maxLength')
                identity='format_'+hashlib.sha256(data).hexdigest()[:24]
                error.length_feedback=[{'role':'assistant','content':None,'tool_calls':[{
                    'id':identity,'type':'function','function':{'name':name,'arguments':arguments}}]},
                    {'role':'tool','tool_call_id':identity,'content':json.dumps({
                        'operation':'format_only_review_feedback_v1',
                        'validation_response':'rejected_schema','fields':fields,'worker_tool_executed':False,
                        'review_acceptance_by_proxy':False,
                        'instruction':'Submit NEW schema-valid review arguments once. Shorten ONLY the listed overlong fields; keep every other argument identical. Use a shorter actual quote substring from the same observed source line when needed. Preserve factual findings, verdict, identifiers, line references and snapshot. Do not drop findings or infer approval. No tool executed and no verdict was accepted.'})}]
                raise error
            # Validator messages/values can contain secrets. Export only a
            # fixed keyword, never instance values, paths or exception text.
            allowed={'type','required','additionalProperties','enum','minLength','maxLength','maxItems'}
            keyword=next(iter(violations)).validator
            reject('schema_'+(keyword if keyword in allowed else 'violation'))
        validate_review_feedback_identity(body,decision)
        validate_remediation_feedback_identity(body,decision)
        validate_r3_feedback_identity(body,decision)
        plan_length_feedback.validate_identity(body,decision)
        phase='adapter'
        text=json.dumps(decision,sort_keys=True,separators=(',',':'),allow_nan=False)
        common={'id':'chatcmpl-typed-'+hashlib.sha256(data).hexdigest()[:24],
                'model':body.get('model',''),'created':0}
        # This is an explicit typed-protocol adapter, never a tool result or an
        # agent execution receipt. Model-supplied values are preserved exactly.
        if media_type.startswith('text/event-stream'):
            frames=[{'choices':[{'index':0,'delta':{'role':'assistant','content':text},'finish_reason':None}]},
                    {'choices':[{'index':0,'delta':{},'finish_reason':'stop'}]}]
            output=(''.join('data: '+json.dumps({**common,'object':'chat.completion.chunk',**f})+'\n\n' for f in frames)+'data: [DONE]\n\n').encode()
        else:output=json.dumps({**common,'object':'chat.completion','choices':[{'index':0,'message':{'role':'assistant','content':text},'finish_reason':'stop'}]}).encode()
        receipt=dict(operation='validated_typed_decision_adapter_v1',
            schema_sha256=hashlib.sha256(json.dumps(schema,sort_keys=True).encode()).hexdigest(),
            upstream_sha256=hashlib.sha256(data).hexdigest(),arguments_sha256=hashlib.sha256(arguments.encode()).hexdigest(),
            output_sha256=hashlib.sha256(output).hexdigest(),model_values_preserved=True,
            worker_tool_executed=False,delivery_approval=False)
        if name==REVIEW_NAME:
            receipt.update(mode='test_review',manifest_sha256=decision['manifest_sha256'],
                           review_acceptance_by_proxy=False)
        if name==EVIDENCE_NAME:
            receipt.update(mode='deployment_evidence',evidence_sha256=decision['evidence_sha256'],
                release_homologated=False,independent_agent_qa_approval=False)
        if name==VALIDATION_NAME:
            receipt.update(mode='deployment_validation_request',evidence_sha256=decision['evidence_sha256'],
                validation_executed=False,release_homologated=False)
        if name==RECOVERY_NAME:
            digests={v for m in body['messages'] if m.get('role')=='user' and isinstance(m.get('content'),str)
                for v in re.findall(r'^'+RECOVERY_MARKER+r':([a-f0-9]{64})$',m['content'],re.M)}
            if len(digests)!=1:reject('recovery_binding')
            receipt.update(mode='worker_recovery_request',recovery_evidence_sha256=next(iter(digests)),
                           author_retry_authorized=False,validation_executed=False)
        if name==REMEDIATION_NAME:
            receipt.update(mode='technical_remediation_plan_or_review',execution_authorized=False,
                           release_homologated=False,plan_acceptance_by_proxy=False)
        if name==R3_NAME:
            receipt.update(mode='r3_incident_diagnosis_or_review',execution_authorized=False,
                           release_homologated=False,diagnosis_acceptance_by_proxy=False)
        return output,media_type,receipt
    except Exception as error:
        if not isinstance(error,StructuredResponseRejected):
            error=StructuredResponseRejected('typed_'+phase+'_invalid')
        if diagnostic is not None:
            error.diagnostic=diagnostic
        error.receipt=dict(operation='rejected_typed_decision_adapter_v1',
            category=error.category,upstream_sha256=hashlib.sha256(data).hexdigest(),
            delivery_approval=False,worker_tool_executed=False,
            response_shape=response_shape(body,data,media_type))
        if diagnostic is not None:
            error.receipt['constraint_diagnostic']=diagnostic
        raise error from None


def record(counter_path,execution_id,receipt):
    from deterministic_read_dispatch import ledger
    if not isinstance(execution_id,str) or not re.fullmatch(r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}',execution_id):
        raise ValueError('correlated typed execution required')
    table=('typed_decision_rejections' if receipt.get('operation')=='rejected_typed_decision_adapter_v1'
           else 'typed_decisions')
    with ledger(counter_path) as con:
        con.execute('CREATE TABLE IF NOT EXISTS '+table+'('
            'execution_id TEXT,upstream_sha256 TEXT,receipt TEXT,PRIMARY KEY(execution_id,upstream_sha256))')
        encoded=json.dumps(receipt,sort_keys=True)
        key=(execution_id,receipt['upstream_sha256'])
        prior=con.execute('SELECT receipt FROM '+table+' WHERE execution_id=? AND upstream_sha256=?',key).fetchone()
        if prior:
            if prior[0]!=encoded:raise ValueError('typed decision receipt drift')
        else:con.execute('INSERT INTO '+table+' VALUES(?,?,?)',(*key,encoded))
