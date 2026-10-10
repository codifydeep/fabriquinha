"""One model-authored format repair of a nonauthorizing technical proposal."""
import copy
import hashlib
import json
import re
from jsonschema import Draft202012Validator
from structured_response_contract import StructuredResponseRejected

OPERATION='format_only_technical_optional_files_feedback_v1'
MARKER='DELIVERY_OPTIONAL_FILES_FORMAT_FEEDBACK_V1'


def enabled(body):
    if body.get('tool_choice')!={'type':'function','function':{'name':'submit_delivery_decision'}}:return False
    tools=body.get('tools',[])
    if len(tools)!=1:return False
    function=tools[0].get('function',{});spec=function.get('parameters',{})
    if (function.get('strict') is not True or set(spec.get('properties',{}))!={'action','reason','optional_files'}
            or spec['properties']['optional_files'].get('maxItems')!=0
            or not any(m.get('role')=='user' and isinstance(m.get('content'),str)
                and re.search(r'^DELIVERY_TYPED_DECISION_V1$',m['content'],re.M)
                and re.search(r'^DELIVERY_STRUCTURED_DECISION_V1:technical$',m['content'],re.M)
                for m in body.get('messages',[]))):return False
    if not any(m.get('role')=='user' and isinstance(m.get('content'),str)
            and re.search(r'^'+MARKER+r'$',m['content'],re.M) for m in body.get('messages',[])):return False
    from decision_schema import apply as schema
    try:expected=schema(copy.deepcopy(body))['response_format']['json_schema']['schema']
    except (ValueError,KeyError,TypeError):return False
    return expected==spec


def opt_in(body):
    """Controller configuration opts in only after complete two-tree reads."""
    from artifact_read_evidence import observations
    paths={p for m in body.get('messages',[]) if m.get('role')=='user' and isinstance(m.get('content'),str)
        for p in re.findall(r'^DELIVERY_REVIEW_READ_PATH:(/evidence/(?:candidate|previous)/[A-Za-z0-9_./-]+)$',m['content'],re.M)}
    if not paths or not all(any(p.startswith('/evidence/'+tree+'/') for p in paths) for tree in ('candidate','previous')):
        return body
    reads=observations(body['messages'],wire=True)
    if any(type(reads.get(p,{}).get('lines')) is not int or reads[p]['lines']<=0
            or reads[p]['lines']!=reads[p].get('total_lines') for p in paths):return body
    candidate=copy.deepcopy(body)
    candidate['messages'].append(dict(role='user',content=MARKER))
    return candidate if enabled(candidate) else body


def make(body,violations,decision,schema,arguments,data):
    if (not enabled(body) or not isinstance(decision,dict)
            or decision.get('action') not in ('request_test_revision','escalate_cto')
            or not violations or any(v.validator!='maxItems' or list(v.path)!=['optional_files']
                or v.validator_value!=0 for v in violations)
            or not isinstance(decision.get('optional_files'),list)
            or not 1<=len(decision['optional_files'])<=8
            or any(not isinstance(p,str) or not 1<=len(p)<=200 for p in decision['optional_files'])):return None
    check=copy.deepcopy(decision);check['optional_files']=[]
    if not Draft202012Validator(schema).is_valid(check):return None
    identity='format_'+hashlib.sha256(data).hexdigest()[:24]
    return [dict(role='assistant',content=None,tool_calls=[dict(id=identity,type='function',
        function=dict(name='submit_delivery_decision',arguments=arguments))]),
        dict(role='tool',tool_call_id=identity,content=json.dumps(dict(operation=OPERATION,
            field='optional_files',maxItems=0,worker_tool_executed=False,delivery_approval=False,
            instruction='Submit new arguments once with optional_files=[]. Preserve action and reason EXACTLY. '
            'File names are not a permitted way to request a test revision. No file is edited, no test '
            'change is authorized, and no decision has been accepted. Do not switch verdict or hypothesis.')))]


def validate_identity(body,decision):
    if len(body.get('messages',[]))<2:return
    submitted,reply=body['messages'][-2:]
    if reply.get('role')!='tool' or not isinstance(reply.get('content'),str):return
    try:payload=json.loads(reply['content'])
    except ValueError:return
    if not isinstance(payload,dict) or payload.get('operation')!=OPERATION:return
    try:
        call=submitted['tool_calls'][0]
        if (not enabled(body) or submitted.get('role')!='assistant' or len(submitted['tool_calls'])!=1
                or call['id']!=reply.get('tool_call_id') or call['function']['name']!='submit_delivery_decision'):
            raise ValueError()
        previous=json.loads(call['function']['arguments'])
        expected={**previous,'optional_files':[]}
        if previous.get('action') not in ('request_test_revision','escalate_cto') or expected!=decision:
            raise ValueError()
    except (ValueError,KeyError,IndexError,TypeError):
        raise StructuredResponseRejected('typed_optional_files_feedback_identity_drift') from None
