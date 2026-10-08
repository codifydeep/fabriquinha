"""Haiku named-tool routing compatibility; local contracts remain authoritative.

Provider hints and a review-only schema projection change on the wire. The
canonical schema remains intact for local validation; no verdict is accepted
by this adapter. Unsupported provider unions never waive local constraints.
"""
import copy


def wire(body):
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
    if name=='submit_test_review':
        function=next(t['function'] for t in result['tools'] if t.get('function',{}).get('name')==name)
        schema=function.get('parameters',{})
        if not schema.get('anyOf'):return result
        if (function.get('strict') is not True or schema.get('type')!='object'
                or set(schema.get('properties',{}))!={'action','reason','optional_files','manifest_sha256','findings'}
                or schema['properties']['action'].get('enum')!=['approve_test_revision','reject_test_revision']
                ):
            raise ValueError('canonical immutable review required for union projection')
        # Haiku rejects anyOf tool schemas even with strict=False. Only the
        # upstream projection omits unions; translate() validates the original
        # schema, including observed citations and action/finding consistency.
        def project(value):
            if isinstance(value,dict):return {k:project(v) for k,v in value.items() if k!='anyOf'}
            if isinstance(value,list):return [project(v) for v in value]
            return value
        function['parameters']=project(schema)
    return result
