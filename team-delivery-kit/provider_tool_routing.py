"""Haiku named-tool routing compatibility; local contracts remain authoritative.

Provider hints and a review-only schema projection change on the wire. The
canonical schema remains intact for local validation; no verdict is accepted
by this adapter. Unsupported provider unions never waive local constraints.
"""
import copy
import json
import re


def project_unions(value):
    """Provider-only representation; never replace the local validator input."""
    if isinstance(value,dict):return {k:project_unions(v) for k,v in value.items() if k!='anyOf'}
    if isinstance(value,list):return [project_unions(v) for v in value]
    return value


def explain_unions(result,schema):
    """Expose removed choice constraints, never select a verdict or citation."""
    actions=[]
    for branch in schema['anyOf']:
        props=branch['properties']; findings=props['findings']
        actions.append(dict(action=props['action']['enum'],
            minItems=findings.get('minItems',0),maxItems=findings.get('maxItems',3),
            kinds=findings['items']['properties']['kind']['enum']))
    locations=schema['properties']['findings']['items'].get('anyOf',[])
    hints=dict(actions=actions,locations=locations,verdict_accepted=False)
    encoded=json.dumps(hints,separators=(',',':'),ensure_ascii=True)
    if len(encoded)>550000:raise ValueError('union explanation exceeds fixed bound')
    result['messages'].append(dict(role='system',content=
        'PROVIDER_UNION_CONSTRAINTS_V1\n'
        'The wire schema omits unions, but the unchanged local validator requires these choices. '
        'Respect the action-specific findings count and kinds. Each citation must copy tree/path/test/line/quote '
        'from ONE complete location choice, not mix choices or paraphrase its quote. '
        'These are observed locations, not findings or approval. Decide independently from the read artifacts. '
        'Do not invent a finding to fill the schema. No verdict has been accepted.\n'+encoded))


def wire(body):
    fmt=body.get('response_format') or {}
    contract=fmt.get('json_schema') or {}
    if (body.get('model')=='anthropic/claude-haiku-5.5'
            and fmt.get('type')=='json_schema'
            and contract.get('name')=='delivery_qa_diagnosis_v1'):
        schema=contract.get('schema') or {}
        props=schema.get('properties') or {}
        fields={'decision','root_cause','editable_code_files','new_test_file','acceptance'}
        if (contract.get('strict') is not True or body.get('tool_choice')!='none'
                or (body.get('provider') or {}).get('require_parameters') is not True
                or schema.get('type')!='object' or set(props)!=fields
                or set(schema.get('required',[]))!=fields
                or schema.get('additionalProperties') is not False
                or props['decision']!={'type':'string','enum':['repair','blocked']}):
            raise ValueError('canonical QA diagnosis required for union projection')
        branches=[]
        for decision in ('blocked','repair'):
            branch=copy.deepcopy(props)
            branch['decision']['enum']=[decision]
            if decision=='blocked':
                branch['editable_code_files']['maxItems']=0
                branch['new_test_file']['enum']=['']
                branch['acceptance']['maxItems']=0
            else:
                branch['editable_code_files']['minItems']=1
                branch['new_test_file']['minLength']=1
                branch['acceptance']['minItems']=1
            branches.append({'type':'object','properties':branch,
                             'required':schema['required'],'additionalProperties':False})
        if schema.get('anyOf')!=branches:
            raise ValueError('canonical QA branch constraints required')
        result=copy.deepcopy(body)
        # The provider sees one object schema; the unchanged canonical union
        # validates every returned byte locally before any diagnostic handoff.
        del result['response_format']['json_schema']['schema']['anyOf']
        result.pop('tools',None)
        result.pop('parallel_tool_calls',None)
        return result
    choice=body.get('tool_choice')
    if (body.get('model')!='anthropic/claude-haiku-5.5'
            or not isinstance(choice,dict) or choice.get('type')!='function'
            or (body.get('provider') or {}).get('require_parameters') is not True):return body
    name=(choice.get('function') or {}).get('name')
    selected=[t for t in body.get('tools',[]) if (t.get('function') or {}).get('name')==name]
    if not isinstance(name,str) or not name or len(selected)!=1:
        raise ValueError('exact forced tool registry required for routing compatibility')
    result=copy.deepcopy(body)
    result['provider']['require_parameters']=False
    if name=='submit_delivery_decision' and any(m.get('role')=='user' and isinstance(m.get('content'),str)
            and re.search(r'^DELIVERY_REVIEW_RECONSIDERATION_V1$',m['content'],re.M)
            for m in body.get('messages',[])):
        from decision_schema import apply as decision_schema
        from typed_decision_contract import apply as typed_contract
        function=next(t['function'] for t in result['tools'] if t.get('function',{}).get('name')==name)
        schema=function.get('parameters',{})
        # Compare with the whole regenerated contract, not only field names.
        # Mandatory observed reads and action/citation unions remain canonical.
        canonical=typed_contract(decision_schema(copy.deepcopy(body)))
        expected=canonical.get('tools',[{}])[0].get('function',{})
        if (function.get('strict') is not True or expected.get('name')!=name
                or expected.get('parameters')!=schema or not schema.get('anyOf')
                or set(schema.get('properties',{}))!={'action','reason','optional_files','findings'}
                or schema['properties']['action'].get('enum')!=['request_test_revision','escalate_cto','request_review_reconsideration']):
            raise ValueError('canonical read-only mediation required for union projection')
        function['parameters']=project_unions(schema)
        explain_unions(result,schema)
    if name=='submit_test_review':
        function=next(t['function'] for t in result['tools'] if t.get('function',{}).get('name')==name)
        schema=function.get('parameters',{})
        if not schema.get('anyOf'):return result
        if (function.get('strict') is not True or schema.get('type')!='object'
                or set(schema.get('properties',{}))!={'action','reason','optional_files','manifest_sha256','findings'}
                or schema['properties']['action'].get('enum')!=['approve_test_revision','reject_test_revision']
                ):
            raise ValueError('canonical immutable review required for union projection')
        from decision_schema import apply as decision_schema
        from typed_decision_contract import apply as typed_contract
        canonical=typed_contract(decision_schema(copy.deepcopy(body)))
        expected=canonical.get('tools',[{}])[0].get('function',{})
        if expected.get('name')!=name or expected.get('parameters')!=schema:
            raise ValueError('complete canonical immutable review required')
        # Haiku rejects anyOf tool schemas even with strict=False. Only the
        # upstream projection omits unions; translate() validates the original
        # schema, including observed citations and action/finding consistency.
        function['parameters']=project_unions(schema)
        explain_unions(result,schema)
    return result
