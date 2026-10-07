"""One format-only correction for nonexecuting plans; never relax the schema."""
import copy
import hashlib
import json
import re
from jsonschema import Draft202012Validator
from structured_response_contract import StructuredResponseRejected,_unique

NAME='submit_remediation_contract'
MARKER='DELIVERY_REMEDIATION_PLAN_LENGTH_FEEDBACK_V1'
OPERATION='format_only_remediation_plan_feedback_v1'


def enabled(body):
    tools=body.get('tools',[])
    if body.get('tool_choice')!={'type':'function','function':{'name':NAME}} or len(tools)!=1:return False
    props=tools[0].get('function',{}).get('parameters',{}).get('properties',{})
    return (props.get('action',{}).get('enum')==['propose_remediation_plan','retain_hold']
        and all(props.get(k,{}).get('enum')==[False] for k in ('execution_authorized','release_homologated'))
        and any(m.get('role')=='user' and isinstance(m.get('content'),str)
            and re.search(r'^'+MARKER+r'$',m['content'],re.M) for m in body.get('messages',[])))


def allowed(path,limit):
    return (path==['reason'] and limit==600 or len(path)==3 and path[0]=='steps'
        and type(path[1]) is int and 0<=path[1]<=2 and path[2]=='objective' and limit==240)


def feedback(body,violations,decision,schema,arguments,data):
    if not enabled(body) or not 1<=len(violations)<=4:return None
    fields=[];validation_only=copy.deepcopy(decision)
    for error in violations:
        path=list(error.path);limit=error.validator_value
        if (error.validator!='maxLength' or not allowed(path,limit) or not isinstance(error.instance,str)
                or not limit<len(error.instance)<=4000):return None
        target=validation_only
        for part in path[:-1]:target=target[part]
        target[path[-1]]='x'  # Validation-only dummy; never submitted/accepted.
        fields.append(dict(path=path,maxLength=limit,actualLength=len(error.instance)))
    if not Draft202012Validator(schema).is_valid(validation_only):return None
    identity='format_plan_'+hashlib.sha256(data).hexdigest()[:24]
    return [dict(role='assistant',content=None,tool_calls=[dict(id=identity,type='function',
        function=dict(name=NAME,arguments=arguments))]),dict(role='tool',tool_call_id=identity,
        content=json.dumps(dict(operation=OPERATION,fields=fields,worker_tool_executed=False,plan_acceptance_by_proxy=False,
        instruction='Submit NEW valid arguments once. Shorten ONLY the listed overlong prose fields, '
        'reason target300characters, objective target120characters. Preserve all other arguments exactly: '
        'action, evidence, step IDs, dependencies, scopes, criteria and flags. No plan or action was approved/executed.')))]


def validate_identity(body,decision):
    if not enabled(body) or len(body.get('messages',[]))<2:return
    submitted,reply=body['messages'][-2:]
    if reply.get('role')!='tool' or not isinstance(reply.get('content'),str):return
    try:receipt=json.loads(reply['content'])
    except ValueError:return
    if not isinstance(receipt,dict) or receipt.get('operation')!=OPERATION:return
    try:
        calls=submitted['tool_calls'];call=calls[0]
        if (submitted.get('role')!='assistant' or len(calls)!=1 or call['id']!=reply.get('tool_call_id')
                or call['function']['name']!=NAME):raise ValueError()
        previous=json.loads(call['function']['arguments'],object_pairs_hook=_unique)
        expected=copy.deepcopy(previous)
        fields=receipt['fields']
        if not 1<=len(fields)<=4:raise ValueError()
        seen=set()
        for field in fields:
            path=field['path'];key=tuple(path)
            if key in seen or not allowed(path,field['maxLength']):raise ValueError()
            seen.add(key);old=previous;wanted=expected;new=decision
            for part in path[:-1]:old=old[part];wanted=wanted[part];new=new[part]
            if len(old[path[-1]])!=field['actualLength'] or not field['maxLength']<len(old[path[-1]])<=4000:raise ValueError()
            wanted[path[-1]]=new[path[-1]]
        if expected!=decision:raise ValueError()
    except (ValueError,KeyError,TypeError,IndexError):
        raise StructuredResponseRejected('typed_plan_feedback_identity_drift') from None
